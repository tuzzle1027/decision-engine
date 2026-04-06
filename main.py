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

def normalize_query(raw_text: str) -> str:
    """LLM으로 사용자 입력 정규화 + 보드 옵션 힌트 기반 조건 추출"""

    # ── 멀티 제품 감지 (소파 책상 추천해줘 등) ──
    normalize_query._multi_products = []
    KNOWN_PRODUCTS = [
        '소파', '쇼파', '침대', '매트리스', '책상', '의자', '식탁', '옷장',
        '서랍장', '책장', '커튼', '러그', '카페트', '조명', '노트북', '냉장고',
        '청소기', '헤드폰', '이어폰', '수영복', '운동화', '러닝화',
    ]
    # 소파베드/소파침대는 단일 제품으로 먼저 체크 (소파+침대 멀티 오감지 방지)
    SINGLE_COMPOUND = ['소파베드', '소파침대']
    is_compound = any(kw in raw_text for kw in SINGLE_COMPOUND)
    if not is_compound:
        # 복합어 제거 후 남은 텍스트에서 감지 (소파침대→소파+침대 오감지 방지)
        clean_text = raw_text
        for compound in SINGLE_COMPOUND:
            clean_text = clean_text.replace(compound, '')
        found = [p for p in KNOWN_PRODUCTS if p in clean_text]
        # 중복 제거 (소파/쇼파 같은 동의어)
        seen = set()
        unique_found = []
        for p in found:
            canonical = '소파' if p == '쇼파' else p
            if canonical not in seen:
                seen.add(canonical)
                unique_found.append(p)
        found = unique_found
        # 2개 이상 감지 + 세트 제외
        SET_PAIRS = {('침대', '매트리스'), ('매트리스', '침대')}
        if len(found) >= 2:
            pair = tuple(found[:2])
            if pair not in SET_PAIRS:
                normalize_query._multi_products = found[:2]
                return raw_text

    # 제품 키워드로 보드 옵션 힌트 준비
    options_section = ''
    try:
        from situation_layer.boards.board_furniture import get_all_options
        PRODUCT_KEYWORDS = {
            '소파': ['소파', '쇼파'], '침대': ['침대'], '책상': ['책상'],
            '옷장': ['옷장'], '서랍장': ['서랍장'], '책장': ['책장'],
            '식탁': ['식탁'], '의자': ['의자'], '커튼': ['커튼'],
            '러그': ['러그'], '매트리스': ['매트리스'],
        }
        for prod, keywords in PRODUCT_KEYWORDS.items():
            if any(kw in raw_text for kw in keywords):
                opts = get_all_options(prod)
                if opts:
                    lines = [f'{k}: {"/".join(v)}' for k, v in opts.items() if v]
                    options_section = f"""
아래는 [{prod}] 보드의 실제 옵션값입니다. 조건 추출 시 반드시 이 값으로 매핑하세요:
""" + '\n'.join(lines)
                break
    except Exception:
        pass

    prompt = f"""쇼핑 AI입니다. 사용자 입력에서 제품명과 이미 결정된 조건을 분리하세요.

출력 형식: 제품명 | 조건이름=값
조건 없으면 제품명만 출력.
{options_section}
핵심 규칙:
사용자 표현의 의미를 파악해서 보드 옵션값으로 정확히 매핑하세요.
하드코딩된 단어 목록이 아니라 의미 기반으로 판단하세요.
보드 옵션 목록이 있으면 반드시 그 중에서 선택하세요.

가성비 규칙:
가성비/저렴한/cheap/budget 등의 표현은 가격=저가로만 변환하세요.

예를 들어:
- 앉았을 때 느낌 → 좌방석쿠션 옵션값으로
- 방수/젖어도/물에 강한 → 패브릭기능=방수
- 세탁/청소 가능 여부 → 커버세탁=가능
- 헤드있는/헤드형 → 헤드유무=헤드있음
- 패브릭/천소파 → 소재=패브릭
- 가성비/저렴한 → 가격=저가만

예시:
코너형 패브릭 소파 → 소파 | 형태=코너형 | 소재=패브릭
4인용 방수 세탁 패브릭 소파 → 소파 | 소재=패브릭 | 인원수=4인용 | 패브릭기능=방수 | 커버세탁=가능
헤드있는 싱글 침대 → 침대 | 사이즈=싱글 | 헤드유무=헤드있음
비싸도 좋은 가죽 소파 → 소파 | 소재=가죽 | 가격=고가
가성비 옷장 → 옷장 | 가격=저가

반드시 한 줄만 출력.
입력: {raw_text}
출력:"""
    try:
        result = call_llm(prompt, max_tokens=100).strip()
        result = result.split('\n')[0].strip()
        if not result:
            return raw_text

        parts = [p.strip() for p in result.split('|')]
        product_name = parts[0]
        selected = {}
        for part in parts[1:]:
            if '=' in part:
                k, v = part.split('=', 1)
                selected[k.strip()] = v.strip()

        print(f'[정규화] {raw_text} → {product_name} selected={selected}')

        normalize_query._selected = selected
        if product_name and len(product_name) < 50:
            return product_name
    except Exception as e:
        print(f'[정규화 오류] {e}')
    return raw_text


def make_board_new(raw_text, session=None):
    """새 분리기 + 상황판 모듈로 상황판 생성"""
    if not _NEW_ROUTER_ENABLED:
        return None

    # LLM 정규화에서 추출한 선택된 조건 (route 전에 먼저!)
    selected = getattr(normalize_query, '_selected', {})
    route_result = _route(raw_text, selected=selected)
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

    # 2구역: ZONE_RULES 기반으로 자동 처리
    if zone == '2':
        from situation_layer.boards.board_furniture import get_zone, ZONE_RULES
        rule = ZONE_RULES.get(product, {})

        # selected 충분하면 → zone 3으로 올려서 아래서 처리
        actual_zone = get_zone(product, selected)
        if actual_zone == '3':
            zone = '3'  # ← 핵심! zone 변수를 3으로 변경
        else:
            # context_key 이미 있으면 → sub 선택 (예: 인원수 있으면 소재 물어보기)
            if rule.get('sub_key') and rule.get('context_key') and rule['context_key'] in selected:
                sub_options = rule.get('sub_options', [])
                return {
                    'type': 'context_select',
                    'text': 'CONTEXT_SELECT:' + '/'.join(sub_options)
                }
            # context_key 없으면 → context 선택지 보여줌
            if rule.get('context_options'):
                return {
                    'type': 'context_select',
                    'text': 'CONTEXT_SELECT:' + '/'.join(rule['context_options'])
                }
            # ZONE_RULES에 없는 제품 → router items 사용
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

        # selected에서 context 자동 추출 (ZONE_RULES 기반)
        if not ctx and selected:
            try:
                from situation_layer.boards.board_furniture import resolve_context
                ctx, _ = resolve_context(product, selected, ctx, None)
            except Exception:
                pass

        # 이케아 브랜드면 context에 이케아 반영
        if brand == '이케아' and product in ['소파', '쇼파']:
            ctx = '이케아'

        board_text = _get_new_board(product, context=ctx, choice=selected)
        print(f'[board_text] product={product} ctx={ctx} → {str(board_text)[:50]}')

        if board_text and board_text.startswith('CONTEXT_SELECT:'):
            return {
                'type': 'context_select',
                'text': board_text
            }

        # [E 직접입력]만 남으면 → make_summary 자동 출력
        if board_text and board_text.strip().replace('조건을 선택해주세요', '').strip().startswith('[E 직접입력]'):
            selections_str = ' '.join([f'{k}:{v}' for k,v in selected.items()])
            summary = make_summary(product, selections_str, session.get('raw_product', product))
            return {'type': 'confirm', 'text': summary + '\n\nCONFIRM_BUTTONS'}
        if board_text and not board_text.startswith('---'):
            # LLM이 만든 엉터리 상황판 제외
            return {
                'type': 'board',
                'text': board_text
            }
        if board_text and board_text.startswith('---'):
            # LLM 폴백 결과 → None 반환해서 기존으로 안 가게
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

    prompt = f"""고객이 찾는 제품 조건을 자연스럽고 따뜻한 한 문장으로 요약하세요.
반드시 아래 형식으로만 출력하세요.

제품: {raw_product}
선택조건: {selections}

형식:
쇼핑 검색 조건이 완성됐어요 고객님! 🛍️
[조건을 자연스러운 한 문장으로 요약 + 이모지]
이 조건으로 제품을 찾아볼까요?

예시출력:
쇼핑 검색 조건이 완성됐어요 고객님! 🛍️
4인용 코너형 흰색 패브릭 소파, 푹신하고 방수되는 제품을 찾으시는군요 🛋️
이 조건으로 제품을 찾아볼까요?"""
    summary = call_llm(prompt, max_tokens=120).strip()
    lines = [l for l in summary.split('\n') if l.strip()]
    if len(lines) >= 3:
        summary = lines[0] + '\n' + lines[1] + '\n' + lines[2]
    elif len(lines) == 2:
        summary = lines[0] + '\n' + lines[1] + '\n이 조건으로 제품을 찾아볼까요?'
    elif lines:
        summary = '쇼핑 검색 조건이 완성됐어요 고객님! 🛍️\n' + lines[0] + '\n이 조건으로 제품을 찾아볼까요?'
    else:
        summary = f"쇼핑 검색 조건이 완성됐어요 고객님! 🛍️\n{raw_product} 찾아드릴게요 😊\n이 조건으로 제품을 찾아볼까요?"

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

    # ── 1단계 최초 입력만 정규화 (context_wait 등은 제외) ──
    if not stage:
        raw_text = normalize_query(raw_text)

    # ── 멀티 제품 감지 → MULTI_SELECT ──
    if not stage:
        multi = getattr(normalize_query, '_multi_products', [])
        if multi:
            session['multi_queue'] = multi[1:]
            session['stage'] = 'multi_wait'
            products_str = '/'.join(multi)
            return f"두 가지 제품을 선택하셨네요! 하나씩 찾아볼까요? 😊\n\nMULTI_SELECT:{products_str}"

    # ── 멀티 대기: 사용자가 MULTI_SELECT에서 선택 ──
    if stage == 'multi_wait':
        session['stage'] = None
        raw_text = normalize_query(raw_text)

    # ── Context 대기: 가정/사무실/업소 선택 → 상황판 진입 ──
    if stage == 'context_wait':
        # context 누적 (어린이→단행본→팝업북 순서 추적)
        prev_context = session.get('context', '')
        session['context'] = raw_text

        if _NEW_ROUTER_ENABLED:
            try:
                # 원래 product 정제
                raw_product = session.get('raw_product', raw_text)
                r = _route(raw_product)
                clean_product = r.get('product', raw_product)

                print(f'[context_wait] clean_product={clean_product} raw_text={raw_text} prev={prev_context}')

                # 원래 product + 선택값(context) + 이전 selected
                auto_selected = session.get('auto_selected', {})
                board_text = _get_new_board(clean_product, context=raw_text, choice=auto_selected)
                print(f'[context_wait board] {str(board_text)[:60]}')

                # CONTEXT_SELECT면 계속 선택 진행
                if board_text and board_text.startswith('CONTEXT_SELECT:'):
                    return board_text

                # 상황판 나오면 완료
                if board_text and not board_text.startswith('CONTEXT_SELECT:'):
                    session['stage'] = 'board_shown'
                    return board_text
            except Exception as e:
                print(f'[context_wait 오류] {e}')

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

    # ── 추가 조건 즉시 처리 ('추가 XXX' 형태면 stage 무관하게 바로 검색) ──
    if raw_text.startswith('추가 ') and len(raw_text) > 3 and stage in ['confirm', 'confirm_add']:
        extra = raw_text[3:].strip()
        session['stage'] = 'selected'
        return make_recommendation(
            session.get('product_name', ''),
            session.get('selections', ''),
            extra=extra,
            session=session
        )

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
            # '추가 배송 빠른 제품' 처럼 추가 뒤에 내용이 있으면 바로 검색
            extra = raw_text
            for prefix in ['추가 ', '추가:', '추가:']:
                if raw_text.startswith(prefix):
                    extra = raw_text[len(prefix):].strip()
                    break
            if extra and extra not in ['추가', '더', '그리고', '또', 'add']:
                session['stage'] = 'selected'
                return make_recommendation(
                    session.get('product_name', ''),
                    session.get('selections', ''),
                    extra=extra,
                    session=session
                )
            # 추가 내용 없으면 그냥 네로 처리
            session['stage'] = 'selected'
            return make_recommendation(
                session.get('product_name', ''),
                session.get('selections', ''),
                session=session
            )
        # "아니요" → 상황판 다시
        else:
            session['stage'] = None
            session['selections'] = ''
            board_result = make_board(session.get('raw_product', raw_text), session)
            session['stage'] = 'board_shown'
            return "다시 선택해주세요 😊\n\n" + board_result['text']

    # ── 추천 완료 후 멀티 큐 다음 제품 연결 ──
    if stage == 'selected':
        queue = session.get('multi_queue', [])
        if queue:
            next_product = queue.pop(0)
            session['multi_queue'] = queue
            session['stage'] = 'multi_wait'
            return f"{next_product}도 찾아드릴까요? 😊\n\nMULTI_SELECT:{next_product}"

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
        # selected 저장 → context_wait에서 3구역 보드에 전달
        session['auto_selected'] = getattr(normalize_query, '_selected', {})
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
