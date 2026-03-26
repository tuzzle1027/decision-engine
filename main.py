# ===============================
# main.py
# Decision Engine v3
# 동현님 설계 / 로드 구현
# ===============================
#
# 3단계 대화형 흐름:
# 1단계: 공감 멘트 + LLM 상황판 (A~E)
# 2단계: LLM 요약 확인 + 버튼 (네/추가/다시)
# 3단계: 제약 감지 + 리뷰 역추적 + Top 3
# ===============================

import os
import json
import urllib.request

from flask import Flask, request, jsonify, send_from_directory

from ocr_layer          import ocr_layer
from product_classifier import classify_product, get_out_of_scope_message
from sensor_layer       import sensor_layer
from policy_layer       import SYSTEM_RULES, POLICE_RULES
from review_collectors  import CollectorManager
from review_engines     import ReviewEngine

# ── API 키 (환경변수에서만 읽기) ──
OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY', '')
APIFY_TOKEN       = os.environ.get('APIFY_TOKEN', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')


# ===============================
# LLM 호출 (Anthropic 우선, OpenAI 폴백)
# ===============================
def call_llm(prompt, system='', max_tokens=1000):
    if ANTHROPIC_API_KEY:
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
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
            return json.loads(res.read())['content'][0]['text']
        except:
            pass

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'max_tokens': max_tokens,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt}
        ]
    }).encode()
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body, headers=headers, method='POST'
    )
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read())['choices'][0]['message']['content']
    except Exception as e:
        return f'[LLM 오류] {e}'


# ===============================
# 제약 감지 → LLM 힌트 (하드코딩 없음)
# ===============================
CONSTRAINT_HINTS = {
    'C4_legal':  '기내 반입 규정/무게/사이즈 관련 주의사항',
    'C3_health': '안전/건강/인증 관련 주의사항',
    'C1_money':  '추가 비용 관련 주의사항',
    'C2_time':   '배송/기간 관련 주의사항',
    'C5_rep':    '신뢰/후기 관련 주의사항',
}

def get_constraint_hint(constraint_interventions):
    if not constraint_interventions:
        return ''
    hints = [CONSTRAINT_HINTS.get(c['constraint'], '') for c in constraint_interventions]
    hints = [h for h in hints if h]
    if hints:
        return f"[제약 감지] {', '.join(hints)}. 추천 전에 이 상황에 맞는 주의사항을 자연스럽게 한 줄 안내해주세요."
    return ''


# ===============================
# Session 초기화
# ===============================
def _init_session(session):
    if session is None:
        session = {}
    session.setdefault('stage', None)        # None → board_shown → confirm → selected
    session.setdefault('product_name', '')
    session.setdefault('raw_product', '')    # 원래 입력값
    session.setdefault('selections', '')     # 상황판 선택값
    session.setdefault('summary', '')        # LLM 요약문
    session.setdefault('turn_count', 0)
    session.setdefault('rejection_count', 0)
    session.setdefault('fatigue', 0)
    session.setdefault('intervention_count', 0)
    session.setdefault('condition_added', False)
    session.setdefault('high_involvement', False)
    return session


# ===============================
# 1단계: 공감 멘트 + LLM 상황판 생성
# ===============================
BOARD_SYSTEM = """당신은 쇼핑 상황판을 만드는 전문가입니다.

[규칙 1] 제품명 분해
- 수식어(아기, 여성용, 휴대용 등)와 핵심명사(독서대, 가방 등)를 분리
- 수식어 있으면 → A = 수식어 관련 속성
- 수식어 없으면 → A = 핵심명사의 용도/목적

[규칙 2] 물리 세계 논리 (절대 위반 금지)
- 독서대 → 패브릭 소재 ❌
- 자동차 → 소재 ❌
- 실제 구매 기준이 되는 속성만

[규칙 3] 속성 배분
- A = 수식어 속성 OR 핵심 용도/목적
- B = 물리적 속성 (소재/방식/타입)
- C = 기능/조건 속성
- D = 예산 (항상 포함, 현실적인 가격대)
- E = 직접입력 (제품 관련 힌트 문구 포함)

[규칙 4] 옵션 품질
- 실제 시장에 존재하는 것만
- 옵션은 서로 명확하게 구분

[출력 형식 - 반드시 지키세요]
BOARD_START
[A 항목명] 옵션1 / 옵션2 / 옵션3
[B 항목명] 옵션1 / 옵션2 / 옵션3
[C 항목명] 옵션1 / 옵션2 / 옵션3
[D 예산] 가격1 / 가격2 / 가격3
[E 직접입력] 힌트문구
BOARD_END"""

def make_board_with_llm(product_name, raw_text):
    """LLM이 상황판 생성 - 물리 세계 논리 적용"""

    # E 직접입력 힌트 - 제품별 변수
    e_hints = {
        '노트북': '"발열 없는 거" "게임할 때 버벅이면 안돼요"',
        '가방':  '"기내 반입 되는 거" "바퀴가 잘 굴러가는 거"',
        '독서대': '"던져도 부서지지 않는 거" "모서리가 날카롭지 않은 거"',
        '유모차': '"한 손으로 접히는 거" "계단에서 들기 편한 거"',
        '카시트': '"설치가 쉬운 거" "아이가 편안한 거"',
    }
    hint = '"직접 입력해주신 한 마디가 더 정확한 제품을 찾아드려요"'
    for k, v in e_hints.items():
        if k in raw_text or k in product_name:
            hint = v
            break

    prompt = f"""제품명: "{raw_text}"

위 제품의 구매 상황판을 만들어주세요.
E 직접입력 힌트: {hint}

반드시 아래 형식으로 출력하세요:
BOARD_START
[A 항목명] 옵션1 / 옵션2 / 옵션3
[B 항목명] 옵션1 / 옵션2 / 옵션3
[C 항목명] 옵션1 / 옵션2 / 옵션3
[D 예산] 가격1 / 가격2 / 가격3
[E 직접입력] {hint}
이런 표현도 다 이해해요 😊
BOARD_END"""

    result = call_llm(prompt, system=BOARD_SYSTEM, max_tokens=400)

    # BOARD_START ~ BOARD_END 추출
    if 'BOARD_START' in result and 'BOARD_END' in result:
        start = result.find('BOARD_START') + len('BOARD_START')
        end   = result.find('BOARD_END')
        return result[start:end].strip()

    # 파싱 실패시 폴백
    return f"""[A 용도] 가정용 / 사무용 / 선물용
[B 소재] 플라스틱 / 나무 / 금속
[C 기능] 기본형 / 기능형 / 프리미엄
[D 예산] 5만원 이하 / 5~15만원 / 15만원 이상
[E 직접입력] {hint}
이런 표현도 다 이해해요 😊"""


# ===============================
# 2단계: LLM 요약 확인
# ===============================
def make_summary(product_name, selections, raw_product, constraint_keys=None):
    """선택값을 자연스러운 문장으로 요약 + 제약 안내 포함"""

    # 제약 안내 생성
    constraint_notice = ''
    if constraint_keys:
        hints = {
            'C3_health': '안전/건강/인증',
            'C4_legal':  '기내 반입 규정/무게/사이즈',
            'C1_money':  '추가 비용',
            'C2_time':   '배송/기간',
        }
        hint_texts = [hints[k] for k in constraint_keys if k in hints]
        if hint_texts:
            notice_prompt = f"""
사용자가 {raw_product}을 찾고 있어요.
감지된 제약: {', '.join(hint_texts)}

아래 형식으로 출력하세요.

⚠️ 이것 꼭 확인하세요!
• 주의사항 1 (구체적 수치/기준 포함)
• 주의사항 2

예시 (아기 제품):
⚠️ 이것 꼭 확인하세요!
• KC 안전 인증 마크가 있는 제품인지 확인하세요
• 모서리 라운드 처리 및 무독성 소재인지 확인하세요

예시 (기내용):
⚠️ 이것 꼭 확인하세요!
• 항공사 기내 반입 기준: 보통 55x40x20cm, 10kg 이하예요
• 초과시 위탁수하물 추가 비용이 발생할 수 있어요
"""
            constraint_notice = call_llm(notice_prompt, max_tokens=150).strip()

    prompt = f"""
사용자가 선택한 조건:
제품: {raw_product}
선택: {selections}

딱 2줄만 출력하세요.
1줄: 선택 내용을 자연스러운 한 문장으로 요약 (이모지 포함)
2줄: "이렇게 찾아드릴까요?"

예시:
"12개월 아기용, 목재 소재, 높이조절 가능한 5만원대 독서대를 찾으시는군요 😊"
이렇게 찾아드릴까요?
"""
    summary = call_llm(prompt, max_tokens=150).strip()

    # 제약 안내를 요약 아래에 붙이기
    if constraint_notice:
        return summary + "\n\n" + constraint_notice
    return summary


# ===============================
# 3단계: 리뷰 역추적 + Top 3 추천
# ===============================
def make_recommendation(product_name, selections, extra='', session=None):
    """제약 감지 + 리뷰 역추적 + Top 3"""
    keyword = product_name + ' ' + selections
    if extra:
        keyword += ' ' + extra

    # 제약 감지 (2단계)
    sel_scores = sensor_layer(selections, session or {})
    step2_interventions = sel_scores.get('constraint_interventions', [])

    # 1단계 + 2단계 합산
    step1_keys = session.get('step1_constraints', [])
    step2_keys = [c['constraint'] for c in step2_interventions]
    all_keys = list(set(step1_keys + step2_keys))

    # 합산 제약 힌트 생성
    all_interventions = [{'constraint': k} for k in all_keys]
    constraint_hint = get_constraint_hint(all_interventions)

    # 리뷰 역추적
    collector = CollectorManager()
    reviews   = collector.collect_all(keyword, count_per_source=5)
    engine    = ReviewEngine()
    analysis  = engine.analyze(reviews, keyword)

    # 제약 안내 LLM 생성 (있을 경우)
    constraint_notice = ''
    if constraint_hint:
        notice_prompt = f"""
사용자가 "{selections}" 조건으로 {product_name}을 찾고 있어요.
{constraint_hint}

딱 2줄만 출력하세요.
1줄: 이모지 + 제약 관련 핵심 주의사항 (구체적인 수치/기준 포함)
2줄: 이 점 확인하고 구매하시면 좋아요!

예시 (기내용):
✈️ 항공사마다 기내 반입 기준이 달라요. 보통 55x40x20cm, 10kg 이하예요.
이 사이즈 초과하면 위탁수하물 추가 비용이 발생할 수 있어요!

예시 (아기):
🔰 아기 제품은 KC 인증 여부와 모서리 안전 처리를 꼭 확인하세요.
무독성 소재인지도 확인하시면 더 안전해요!
"""
        constraint_notice = call_llm(notice_prompt, max_tokens=150).strip()

    prompt = f"""
사용자 조건: {selections}
{f"추가 요청: {extra}" if extra else ""}
찾는 제품: {product_name}

리뷰 역추적:
만족: {analysis.get('satisfied', [])}
아쉬움: {analysis.get('disappointed', [])}
점수: {analysis.get('total_score', 0)}

위 조건에 맞는 제품 Top 3 추천해주세요.
각 제품: 이름 / 가격 / 특징 1줄 / 리뷰 근거
광고 금지, 실제 리뷰 기반으로만
"""
    result = call_llm(prompt, system=SYSTEM_RULES)

    # 제약 안내 앞에 붙이기
    if constraint_notice:
        return constraint_notice + "\n\n" + result
    return result


# ===============================
# Decision Engine 메인
# ===============================
def decision_engine(user_input, session=None):
    session  = _init_session(session)
    ocr      = ocr_layer(user_input)
    if ocr['empty']:
        return "무엇을 찾고 계신가요? 😊"
    raw_text = ocr['clean']
    stage    = session.get('stage')

    # ── 3단계: 확인 후 추가 요청 ──
    if stage == 'confirm_add':
        session['stage'] = 'selected'
        extra = raw_text
        result = make_recommendation(
            session.get('product_name', ''),
            session.get('selections', ''),
            extra=extra,
            session=session
        )
        return result

    # ── 2단계: 확인 버튼 응답 처리 ──
    if stage == 'confirm':
        # "네" → 바로 역추적
        if any(w in raw_text for w in ['네', '예', '맞아', '맞아요', '좋아', '응', 'yes', 'ok']):
            session['stage'] = 'selected'
            return make_recommendation(
                session.get('product_name', ''),
                session.get('selections', ''),
                session=session
            )
        # "추가" → 추가 입력 받기
        elif any(w in raw_text for w in ['추가', '더', '그리고', '또', 'add']):
            session['stage'] = 'confirm_add'
            return "어떤 조건을 추가하시겠어요? 😊\n말씀해주시면 반영해서 찾아드릴게요!"
        # "아니요" → 상황판 다시
        else:
            session['stage'] = None
            session['selections'] = ''
            product = classify_product(raw_text if not session.get('raw_product') else session.get('raw_product'))
            board = make_board_with_llm(session.get('product_name', ''), session.get('raw_product', raw_text))
            session['stage'] = 'board_shown'
            return "다시 선택해주세요 😊\n\n" + board

    # ── 1.5단계: 상황판 선택 완료 → LLM 요약 확인 ──
    if stage == 'board_shown':
        session['stage']      = 'confirm'
        session['selections'] = raw_text

        # 1단계 + 현재 제약 합산
        step1_keys = session.get('step1_constraints', [])
        cur_scores = sensor_layer(raw_text, session)
        cur_keys = [c['constraint'] for c in cur_scores.get('constraint_interventions', [])]
        all_keys = list(set(step1_keys + cur_keys))

        summary = make_summary(
            session.get('product_name', ''),
            raw_text,
            session.get('raw_product', ''),
            constraint_keys=all_keys
        )
        session['summary'] = summary

        # 확인 버튼 3개 포함
        return f"{summary}\n\nCONFIRM_BUTTONS"

    # ── 1단계: 처음 입력 → 공산품 판단 + 공감 + 상황판 ──
    product = classify_product(raw_text)
    if not product['is_product']:
        return get_out_of_scope_message()

    # 센서
    scores = sensor_layer(raw_text, session)
    scores.update({
        'S_type': 'S2', 'I_hat': 0.6, 'activated': True,
        'As': 0.0, 'res_state': 'INTENT', 'anti_type': 'NONE',
        'anti_intervention': {'level': 'LOW', 'action': None, 'message': None}
    })

    # 공감 멘트
    drive = scores.get('Drive', {})
    empathy = call_llm(f"""
사용자가 "{raw_text}" 를 찾고 있어요.
Drive: N={drive.get('N')} W={drive.get('W')} Ψ={drive.get('Psi')}

딱 한 줄만 출력하세요. 따뜻한 공감 + 이모지.
질문이나 상황판 금지.
""", max_tokens=80).strip()

    # LLM 상황판
    board = make_board_with_llm(product.get('product_name', raw_text), raw_text)

    # 1단계 제약 감지 세션 저장
    step1_interventions = scores.get('constraint_interventions', [])
    session['step1_constraints'] = [c['constraint'] for c in step1_interventions]

    session['stage']       = 'board_shown'
    session['product_name'] = product.get('product_name', raw_text)
    session['raw_product'] = raw_text

    return empathy + "\n\n" + board


# ===============================
# Flask 서버
# ===============================
app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    data       = request.json or {}
    user_input = data.get('message', '')
    session    = data.get('session') or {}
    if not user_input:
        return jsonify({'error': 'message required'}), 400
    result = decision_engine(user_input, session)
    return jsonify({'response': result, 'session': session})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'engine': 'Decision Engine v3'})

@app.route('/', methods=['GET'])
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Decision Engine v3 시작 - port {port}")
    app.run(host='0.0.0.0', port=port)
