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

VERSION = 'v15'

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


def _make_board_with_llm(raw_text):
    """situation_layer가 못 잡은 제품 → LLM 상황판 생성 폴백"""
    BOARD_SYSTEM = """당신은 쇼핑 상황판을 만드는 전문가입니다.
실제 구매 기준이 되는 속성만 사용하세요.
물리적으로 불가능한 옵션 절대 금지.
옵션 텍스트 안에 슬래시(/) 절대 사용 금지 (예: 3/4사이즈 ❌ → 3-4사이즈 ✅)

출력 형식 (반드시 지키세요):
BOARD_START
[A 항목명] 옵션1 / 옵션2 / 옵션3
[B 항목명] 옵션1 / 옵션2 / 옵션3
[C 항목명] 옵션1 / 옵션2 / 옵션3
[D 예산] 가격1 / 가격2 / 가격3
[E 직접입력] 원하는 조건을 직접 입력하세요
BOARD_END"""

    prompt = f'제품: "{raw_text}"\n구매 상황판을 만들어주세요.'
    result = call_llm(prompt, system=BOARD_SYSTEM, max_tokens=400)

    if 'BOARD_START' in result and 'BOARD_END' in result:
        start = result.find('BOARD_START') + len('BOARD_START')
        end   = result.find('BOARD_END')
        return result[start:end].strip()

    return f"""[A 용도] 기본형 / 기능형 / 프리미엄
[B 대상] 성인용 / 어린이용 / 공용
[C 기능] 기본 / 접이식 / 고급형
[D 예산] 저가 / 중가 / 고가
[E 직접입력] 원하는 조건을 직접 입력하세요"""


# ===============================
# 1단계: 상황판 (situation_layer)
# ===============================
from situation_engine import DecisionStructureEngine as SituationEngine
_situation = SituationEngine()

# ── 새 분리기 + 상황판 모듈 연결 ──
try:
    from situation_layer.router import route as _route
    from situation_layer.boards import get_board as _get_new_board
    _NEW_ROUTER_ENABLED = True
except Exception as e:
    print(f'[새 라우터 로드 실패] {e}')
    _NEW_ROUTER_ENABLED = False

def make_board_new(raw_text, session=None):
    """새 분리기 + 상황판 모듈로 상황판 생성"""
    if not _NEW_ROUTER_ENABLED:
        return None

    route_result = _route(raw_text)
    zone = route_result.get('zone')
    mode = route_result.get('mode')
    product = route_result.get('product', '')
    brand = route_result.get('brand', '')
    context_val = route_result.get('context', '')

    # 0구역: 브랜드만 → 되물음
    if zone == '0':
        return {
            'type': 'brand_ask',
            'text': route_result.get('message', '어떤 제품 찾으세요? 😊')
        }

    # Direct Mode: 트렌드 키워드 → 바로 검색
    if zone == 'direct':
        return {
            'type': 'direct_search',
            'text': raw_text,
            'product': product
        }

    # Solution Mode: 취미/활동
    if zone == 'solution':
        items = route_result.get('items', [])
        copy = route_result.get('message', '')
        items_text = ' / '.join(items)
        solution_text = copy + "\n\n필요한 것들:\n" + items_text
        return {
            'type': 'solution',
            'text': solution_text,
            'items': items
        }

    # 2구역: large_category / brand_category → Context 선택
    if zone == '2':
        if mode == 'large_category':
            items = route_result.get('items', [])
            return {
                'type': 'context_select',
                'text': 'CONTEXT_SELECT:' + '/'.join(items)
            }
        if mode == 'brand_category':
            # 브랜드+카테고리 → LLM 폴백
            from situation_layer.boards.board_llm import get_board as llm_b
            board_text = llm_b(product=f'{brand} {product}')
            return {
                'type': 'board',
                'text': board_text
            }
        # 일반 context_select
        board_text = _get_new_board(product, context=context_val)
        if board_text and board_text.startswith('CONTEXT_SELECT:'):
            return {
                'type': 'context_select',
                'text': board_text
            }

    # 3구역: 상황판 생성
    if zone == '3' or zone == '2':
        ctx = session.get('context') if session else None
        ctx = ctx or context_val

        # 이케아 브랜드면 context에 이케아 반영
        if brand == '이케아' and product in ['소파', '쇼파']:
            ctx = '이케아'

        board_text = _get_new_board(product, context=ctx)
        if board_text and board_text.startswith('CONTEXT_SELECT:'):
            return {
                'type': 'context_select',
                'text': board_text
            }
        if board_text:
            return {
                'type': 'board',
                'text': board_text
            }

    return None


def make_board(raw_text, session=None):
    """situation_layer로 상황판 생성 - 새 라우터 우선 시도"""

    # 새 라우터 먼저 시도
    new_result = make_board_new(raw_text, session)
    print(f'[라우터 결과] {raw_text[:20]} → {new_result}')
    if new_result:
        return new_result

    # 기존 situation_layer 폴백
    result = _situation.respond(raw_text, session=session or {})
    render = result['render']
    mode   = result['mode']

    # VS Mode 1단계: 설명만 반환 (board 없음)
    if mode == 'vs_mode':
        options = result['sensor_state'].get('options', [])
        return {
            'type': 'vs_explain',
            'text': render.get('explanation', ''),
            'vs_options': options
        }

    # Context 선택 필요: 버튼형으로 렌더링
    if mode == 'context_preselect':
        return {
            'type': 'context_select',
            'text': 'CONTEXT_SELECT:가정/사무실/업소'
        }

    # recommend 모드 = situation_layer가 제품 못 찾은 경우 → LLM 상황판 폴백
    if mode == 'recommend' or not render.get('board'):
        board_text = _make_board_with_llm(raw_text)
        return {
            'type': 'board',
            'text': board_text,
            'mode': 'llm_fallback'
        }

    # 상황판 조합: 설명 + 컬러 + board
    parts = []
    if render.get('explanation'):
        parts.append(render['explanation'])
    if render.get('pre_input'):
        parts.append(render['pre_input'])
    if render.get('color_layer'):
        parts.append(render['color_layer'])
    if render.get('board'):
        parts.append(render['board'])

    return {
        'type': 'board',
        'text': '\n\n'.join(parts),
        'mode': mode
    }


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
선택 조건: {selections}
감지된 제약: {', '.join(hint_texts)}
※ 선택 조건에 특정 항공사/브랜드/상세조건이 있으면 그것에 맞는 구체적인 정보를 안내해주세요.

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
            constraint_notice = call_llm(notice_prompt, max_tokens=200).strip()

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
        constraint_notice = call_llm(notice_prompt, max_tokens=200).strip()

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

    # ── Context 대기: 가정/사무실/업소 선택 → 상황판 진입 ──
    if stage == 'context_wait':
        session['context'] = raw_text
        board_result = make_board(session.get('raw_product', raw_text), session)
        session['stage'] = 'board_shown'
        return board_result['text']

    # ── VS 대기: 사용자가 VS에서 선택 → 상황판 진입 ──
    if stage == 'vs_wait':
        session['vs_choice'] = raw_text
        # 원래 질문 기반으로 상황판 생성 (선택값은 session에서 읽음)
        original = session.get('raw_product', raw_text)
        board_result = make_board(original, session)
        session['stage'] = 'board_shown'
        return board_result['text']

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
            board_result = make_board(session.get('raw_product', raw_text), session)
            session['stage'] = 'board_shown'
            return "다시 선택해주세요 😊\n\n" + board_result['text']

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

    # VS 사전 감지 (product 없어도 통과)
    board_precheck = make_board(raw_text, session)
    is_vs = board_precheck.get('type') == 'vs_explain'

    product = classify_product(raw_text)
    if not product['is_product'] and not is_vs:
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
사용자가 쇼핑 AI에게 "{raw_text}" 라고 입력했어요.
이 사람은 제품을 구매하려고 합니다.
Drive: N={drive.get('N')} W={drive.get('W')} Ψ={drive.get('Psi')}

딱 한 줄만 출력하세요. 구매를 도와준다는 따뜻한 공감 + 이모지.
"찾아드리다", "도와드리다" 같은 쇼핑 문맥 표현 사용.
질문이나 상황판 금지. "잃어버리다" 같은 표현 절대 금지.
""", max_tokens=80).strip()

    # situation_layer 상황판 (VS precheck 재사용)
    board_result = board_precheck

    # 1단계 제약 감지 세션 저장
    step1_interventions = scores.get('constraint_interventions', [])
    session['step1_constraints'] = [c['constraint'] for c in step1_interventions]
    session['product_name'] = product.get('product_name', raw_text)
    session['raw_product']  = raw_text

    # 0구역: 브랜드만 입력 → 되물음
    if board_result['type'] == 'brand_ask':
        return empathy + "\n\n" + board_result['text']

    # Solution Mode: 취미/활동
    if board_result['type'] == 'solution':
        session['stage'] = 'board_shown'
        return empathy + "\n\n" + board_result['text']

    # Direct Mode: 트렌드 검색
    if board_result['type'] == 'direct_search':
        session['stage'] = 'board_shown'
        return empathy + "\n\n" + board_result['text']

    # VS Mode: 설명만 먼저, 상황판 대기
    if board_result['type'] == 'vs_explain':
        session['stage']      = 'vs_wait'
        session['vs_options'] = board_result.get('vs_options', [])
        vs_options_str = '/'.join(board_result.get('vs_options', []))
        vs_text = board_result['text']
        vs_text += f"\n\nVS_SELECT:{vs_options_str}"
        return empathy + "\n\n" + vs_text

    # Context 선택 필요: 버튼형 선택 대기
    if board_result['type'] == 'context_select':
        session['stage'] = 'context_wait'
        return empathy + "\n\n" + board_result['text']

    session['stage'] = 'board_shown'
    return empathy + "\n\n" + board_result['text']


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
    return jsonify({'status': 'ok', 'version': VERSION})

@app.route('/version', methods=['GET'])
def version():
    return jsonify({'version': VERSION})

@app.route('/', methods=['GET'])
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Decision Engine v3 시작 - port {port}")
    app.run(host='0.0.0.0', port=port)
