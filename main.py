# ===============================
# main.py
# Decision Engine 전체 연결
# 동현님 설계 / 로드 구현
# ===============================

import os
import json
import urllib.request

from ocr_layer         import ocr_layer
from product_classifier import classify_product, get_out_of_scope_message
from sensor_layer      import sensor_layer
from policy_layer      import get_policy, build_llm_prompt, SYSTEM_RULES, POLICE_RULES
from ux_layer          import format_response, format_debug
from review_collectors import CollectorManager
from review_engines    import ReviewEngine

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY','')
APIFY_TOKEN    = os.environ.get('APIFY_TOKEN','')

def call_llm(prompt, system='', max_tokens=1000):
    # Anthropic Claude API
    ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    if ANTHROPIC_KEY:
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_KEY,
            'anthropic-version': '2023-06-01'
        }
        body = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': max_tokens,
            'system': system,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body, headers=headers, method='POST'
        )
        try:
            res = urllib.request.urlopen(req)
            result = json.loads(res.read())
            return result['content'][0]['text']
        except Exception as e:
            pass  # 실패시 OpenAI로 폴백

    # OpenAI 폴백
    headers = {'Content-Type':'application/json','Authorization':f'Bearer {OPENAI_API_KEY}'}
    body = json.dumps({'model':'gpt-4o-mini','max_tokens':max_tokens,
                       'messages':[{'role':'system','content':system},
                                   {'role':'user','content':prompt}]}).encode()
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                                  data=body,headers=headers,method='POST')
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read())['choices'][0]['message']['content']
    except Exception as e:
        return f'[LLM 오류] {e}'



# 제약 안내 메시지
CONSTRAINT_MESSAGES = {
    'C3_health': {
        'title': '🔰 안전 정보',
        'messages': [
            '아기/유아 제품은 KC 인증 여부를 꼭 확인하세요!',
            '모서리 안전 처리, 무독성 소재인지 확인하세요.',
            '영·유아용 제품은 안전 인증 마크(KC) 필수예요.'
        ]
    },
    'C4_legal': {
        'title': '✈️ 항공사 기내 반입 기준',
        'messages': [
            '대한항공/아시아나: 55×40×20cm 이하, 10kg 이하',
            '제주항공/진에어: 55×40×20cm 이하, 10kg 이하',
            '이 사이즈 초과시 위탁수하물로 추가 비용 발생해요!'
        ]
    },
    'C1_money': {
        'title': '💰 추가 비용 주의',
        'messages': [
            '구매 전 추가 비용(배송비, 설치비 등) 확인하세요.'
        ]
    }
}

def get_constraint_notice(constraint_interventions):
    """제약 발동시 안내 메시지 생성"""
    if not constraint_interventions:
        return ''
    notices = []
    for item in constraint_interventions:
        key = item['constraint']
        if key in CONSTRAINT_MESSAGES:
            c = CONSTRAINT_MESSAGES[key]
            notice = c['title'] + '\n'
            notice += '\n'.join(['• ' + m for m in c['messages']])
            notices.append(notice)
    return '\n\n'.join(notices)


def make_situation_board(raw_text, product):
    """
    상황판 코드로 직접 생성
    LLM 없음 → 무조건 상황판 출력
    사용자 입력 기반으로 카테고리 자동 감지
    """
    name = (product.get('product_name','') + ' ' + raw_text).lower()

    # 카테고리별 상황판 정의
    if any(k in name for k in ['노트북','laptop','컴퓨터','태블릿','모니터','키보드']):
        rows = [
            ("[A 용도]", "업무용 / 학생용 / 게임용"),
            ("[B 화면크기]", "13인치 이하 / 15인치 / 17인치 이상"),
            ("[C 예산]", "50만원 이하 / 50~100만원 / 100만원 이상"),
        ]
    elif any(k in name for k in ['냉장고','세탁기','에어컨','청소기','공기청정기','tv']):
        rows = [
            ("[A 용량/크기]", "소형 / 중형 / 대형"),
            ("[B 브랜드]", "삼성 / LG / 기타"),
            ("[C 예산]", "50만원 이하 / 50~100만원 / 100만원 이상"),
        ]
    elif any(k in name for k in ['가방','백팩','캐리어','지갑','파우치']):
        rows = [
            ("[A 용도]", "여행용 / 출퇴근용 / 일상용"),
            ("[B 사이즈]", "소형 / 중형 / 대형"),
            ("[C 예산]", "3만원 이하 / 3~10만원 / 10만원 이상"),
        ]
    elif any(k in name for k in ['신발','운동화','구두','슬리퍼','샌들']):
        rows = [
            ("[A 용도]", "운동용 / 출퇴근용 / 일상용"),
            ("[B 사이즈]", "240 이하 / 245~260 / 265 이상"),
            ("[C 예산]", "5만원 이하 / 5~15만원 / 15만원 이상"),
        ]
    elif any(k in name for k in ['의자','책상','소파','침대','매트리스']):
        rows = [
            ("[A 용도]", "사무용 / 게이밍 / 학습용"),
            ("[B 소재]", "패브릭 / 가죽 / 메쉬"),
            ("[C 예산]", "10만원 이하 / 10~30만원 / 30만원 이상"),
        ]
    else:
        # 기본 상황판
        rows = [
            ("[A 용도]", "가정용 / 사무용 / 선물용"),
            ("[B 사이즈]", "소형 / 중형 / 대형"),
            ("[C 예산]", "5만원 이하 / 5~20만원 / 20만원 이상"),
        ]

    lines = [f"{label} {options}" for label, options in rows]
    lines.append("[D 직접입력] 원하는 조건을 직접 입력하세요")
    return "\n".join(lines)


def _init_session(session):
    """session 키 빠진 것 채우기 - None이든 빈값이든 안전하게"""
    if session is None:
        session = {}
    session.setdefault('turn_count', 0)
    session.setdefault('rejection_count', 0)
    session.setdefault('fatigue', 0)
    session.setdefault('intervention_count', 0)
    session.setdefault('condition_added', False)
    session.setdefault('high_involvement', False)
    return session

def needs_review(policy):
    return policy['action'] in ['SITUATION_BOARD']

def extract_keyword(raw_text, scores):
    if scores.get('S_type') == 'S2':
        stopwords = ['찾아줘','추천해줘','알아봐줘','구매','사고싶어','필요해']
        kw = raw_text
        for sw in stopwords:
            kw = kw.replace(sw,'').strip()
        return kw or raw_text
    return raw_text

def police_check(output, scores):
    prompt = f"S_type={scores.get('S_type')},I_hat={scores.get('I_hat')},Conflict={scores.get('Conflict')}\n출력:{output[:200]}\n체크:"
    return call_llm(prompt, system=POLICE_RULES, max_tokens=10).strip()

def decision_engine(user_input, session=None, debug=False):
    # session 안전하게 초기화 (None이든 빈값이든)
    session = _init_session(session)

    # STEP 1: OCR (읽기만, LLM 해석 금지)
    ocr = ocr_layer(user_input)
    if ocr['empty']:
        return "무엇을 찾고 계신가요? 😊"
    raw_text = ocr['clean']

    # STEP 2: 단계 확인
    stage = session.get('stage', None)

    # 2단계: 상황판 선택 완료 → 추천
    if stage == 'board_shown':
        selections = raw_text
        session['stage'] = 'selected'
        session['selections'] = selections
        keyword = session.get('product_name', '') + ' ' + selections
        collector = CollectorManager()
        reviews   = collector.collect_all(keyword, count_per_source=5)
        engine    = ReviewEngine()
        analysis  = engine.analyze(reviews, keyword)
        prompt = f"""
사용자가 선택한 조건: {selections}
찾는 제품: {session.get('product_name', '')}

리뷰 역추적 결과:
만족: {analysis.get('satisfied', [])}
아쉬움: {analysis.get('disappointed', [])}
점수: {analysis.get('total_score', 0)}

위 조건에 맞는 제품 Top 3를 추천해주세요.
각 제품: 이름 / 가격 / 특징 1줄 / 리뷰 근거
광고 금지, 실제 리뷰 기반으로만 추천
"""
        return call_llm(prompt, system=SYSTEM_RULES)

    # 공산품 판단 (LLM)
    product = classify_product(raw_text)
    if not product['is_product']:
        return get_out_of_scope_message()

    # STEP 3: 센서 (수치 계산)
    scores = sensor_layer(raw_text, session)

    # 공산품 확인됐으면 쇼핑 의도 있음 → 무조건 SITUATION_BOARD
    if product['is_product']:
        scores['S_type'] = 'S2'
        scores['I_hat'] = 0.6
        scores['activated'] = True
        scores['As'] = 0.0
        scores['res_state'] = 'INTENT'
        scores['anti_type'] = 'NONE'
        scores['anti_intervention'] = {'level': 'LOW', 'action': None, 'message': None}

    # STEP 3: 정책
    policy = get_policy(scores)

    # STEP 4: 리뷰 역추적
    review_result = None
    if needs_review(policy):
        keyword   = extract_keyword(raw_text, scores)
        collector = CollectorManager()
        reviews   = collector.collect_all(keyword, count_per_source=5)
        engine    = ReviewEngine()
        analysis  = engine.analyze(reviews, keyword)
        review_result = {'top3': [], 'keyword': keyword, 'analysis': analysis}

    # STEP 5: 상황판 = 공감 멘트 + 코드 직접 출력
    if policy['action'] == 'SITUATION_BOARD':
        # 공감 멘트 LLM 생성
        drive = scores.get('Drive', {})
        empathy_prompt = f"""
사용자가 "{raw_text}" 를 찾고 있어요.

Drive 분석:
- N(기능 필요): {drive.get('N')}
- W(욕망): {drive.get('W')}
- Ψ(정체성): {drive.get('Psi')}
- 주도: {drive.get('dominant')}

딱 한 줄만 출력하세요.
따뜻하고 자연스러운 공감 한 줄 + 이모지.
상황판이나 질문은 절대 금지.
예시:
- "여행 설레시겠어요 😊 딱 맞는 가방 찾아드릴게요!"
- "노트북 고르기 쉽지 않죠 😅 제가 도와드릴게요!"
- "좋은 냉장고 고르는 거 중요하죠 😊 최적 제품 찾아드릴게요!"
"""
        empathy = call_llm(empathy_prompt, max_tokens=100).strip()
        board = make_situation_board(raw_text, product)
        # 제약 안내 추가
        constraint_notice = get_constraint_notice(scores.get('constraint_interventions', []))
        if constraint_notice:
            output = empathy + "\n\n" + constraint_notice + "\n\n" + board
        else:
            output = empathy + "\n\n" + board
        session['stage'] = 'board_shown'
        session['product_name'] = product.get('product_name', raw_text)
    else:
        prompt = build_llm_prompt(raw_text, scores, policy, review_result)
        output = call_llm(prompt, system=SYSTEM_RULES)

    # STEP 6: 경찰 (상황판은 경찰 체크 건너뜀)
    if policy['action'] != 'SITUATION_BOARD':
        check = police_check(output, scores)
        if check == 'VIOLATION':
            prompt = build_llm_prompt(raw_text, scores, policy, review_result)
            output = call_llm(prompt, system=SYSTEM_RULES)

    # STEP 7: UX
    final = format_response(output, scores, policy, review_result)
    session['turn_count'] += 1
    return final

# ── Flask 서버 ──
from flask import Flask, request, jsonify, send_from_directory
app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    data       = request.json or {}
    user_input = data.get('message','')
    session    = data.get('session', None)
    if not user_input:
        return jsonify({'error':'message required'}),400
    # session을 dict로 초기화해서 변경사항 반영
    if session is None:
        session = {}
    result = decision_engine(user_input, session)
    return jsonify({'response':result,'session':session})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status':'ok','engine':'Decision Engine v3'})

@app.route('/', methods=['GET'])
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Decision Engine v3 시작 - port {port}")
    app.run(host='0.0.0.0', port=port)
