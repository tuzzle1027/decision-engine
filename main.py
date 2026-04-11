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
import re
import urllib.request

from flask import Flask, request, jsonify, send_from_directory

from ocr_layer          import ocr_layer
from product_classifier import classify_product, get_out_of_scope_message
from sensor_layer       import sensor_layer
from policy_layer       import SYSTEM_RULES, POLICE_RULES
from review_collectors  import CollectorManager
from review_engines     import ReviewEngine
from board_vs           import detect_vs, get_vs_first_question, get_vs_next_question

VERSION = 'v15'

# ── API 키 (환경변수에서만 읽기) ──
OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY', '')
APIFY_TOKEN       = os.environ.get('APIFY_TOKEN', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')


def search_instagram_images(keyword: str, limit: int = 6) -> list:
    """
    Apify로 인스타그램 이미지 검색
    returns: [{'url': '...', 'caption': '...'}, ...]
    """
    token = APIFY_TOKEN
    if not token:
        print('[Apify] APIFY_TOKEN 없음')
        return []

    try:
        import json
        import urllib.request

        # Apify Instagram Hashtag Scraper 호출
        hashtag = keyword.replace(' ', '').replace('#', '')
        body = json.dumps({
            "hashtags": [hashtag],
            "resultsLimit": limit,
            "resultsType": "posts",
        }).encode()

        req = urllib.request.Request(
            f'https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/runs?token={token}',
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=30)
        run_data = json.loads(res.read())
        run_id = run_data.get('data', {}).get('id', '')
        dataset_id = run_data.get('data', {}).get('defaultDatasetId', '')

        if not dataset_id:
            print(f'[Apify] run_id={run_id} dataset 없음')
            return []

        # 결과 가져오기 (최대 30초 대기)
        import time
        for _ in range(10):
            time.sleep(3)
            try:
                res2 = urllib.request.urlopen(
                    f'https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}&limit={limit}',
                    timeout=10
                )
                items = json.loads(res2.read())
                if items:
                    images = []
                    for item in items:
                        url = item.get('displayUrl') or item.get('imageUrl', '')
                        caption = item.get('caption', '')[:50] if item.get('caption') else ''
                        if url:
                            images.append({'url': url, 'caption': caption})
                    print(f'[Apify] {keyword} → {len(images)}개 이미지')
                    return images
            except:
                continue

    except Exception as e:
        print(f'[Apify 오류] {e}')
    return []


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

    # ── 멀티 제품 감지 (소파 책상 침대 추천해줘 등) ──
    normalize_query._multi_products = []
    KNOWN_PRODUCTS = [
        '소파', '쇼파', '침대', '매트리스', '책상', '의자', '식탁', '옷장',
        '서랍장', '책장', '커튼', '러그', '카페트', '조명', '노트북', '냉장고',
        '청소기', '헤드폰', '이어폰', '수영복', '운동화', '러닝화',
    ]

    # ── 맥락어+목적 패턴 감지 (멀티 오감지 방지) ──
    # "침대 앞에 둘 러그", "책상 위에서 사용할 조명"
    # → 앞 단어는 맥락, 뒤 단어가 실제 찾는 제품
    CONTEXT_PATTERNS = [
        '에 맞는', '에 놓을', '옆에 놓을', '앞에 놓을', '위에 놓을',
        '앞에 둘', '옆에 둘', '위에 둘',
        '에 사용할', '에 쓸', '에 어울리는', '에 달 ', '에 맞춰',
        '위에서 사용할', '에서 사용할',
    ]
    is_context_pattern = any(p in raw_text for p in CONTEXT_PATTERNS)
    if is_context_pattern:
        normalize_query._sofa_bed_select = False
        normalize_query._multi_products = []
        # 패턴 뒤에 오는 제품 추출
        for pattern in CONTEXT_PATTERNS:
            if pattern in raw_text:
                after = raw_text[raw_text.index(pattern) + len(pattern):].strip()
                for prod in sorted(KNOWN_PRODUCTS, key=len, reverse=True):
                    if prod in after:
                        print(f'[맥락패턴] "{raw_text}" → 목적제품={prod}')
                        return prod  # 목적 제품만 반환
        # 패턴은 있는데 제품 못 찾으면 그냥 진행
    else:
        SINGLE_COMPOUND = ['소파베드', '소파침대', '소파 침대']
        is_compound = any(kw in raw_text for kw in SINGLE_COMPOUND)
        if is_compound and '소파 침대' in raw_text and '소파침대' not in raw_text and '소파베드' not in raw_text:
            normalize_query._multi_products = []
            normalize_query._sofa_bed_select = True
            return raw_text
        normalize_query._sofa_bed_select = False
        if not is_compound:
            clean_text = raw_text
            for compound in SINGLE_COMPOUND:
                clean_text = clean_text.replace(compound, '')
            found = [p for p in KNOWN_PRODUCTS if p in clean_text]
            seen = set()
            unique_found = []
            for p in found:
                canonical = '소파' if p == '쇼파' else p
                if canonical not in seen:
                    seen.add(canonical)
                    unique_found.append(p)
            found = unique_found
            SET_PAIRS = {('침대', '매트리스'), ('매트리스', '침대')}
            if len(found) >= 2:
                pair = tuple(found[:2])
                if pair not in SET_PAIRS:
                    normalize_query._multi_products = found
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

[물리 세계 재료 사전 - 이걸 보고 조건 키를 정확히 판단하세요]
금속/스틸/철재/알루미늄 → 가구 다리/프레임에 사용 → 다리소재=스틸
우드/원목/나무 → 가구 다리/프레임에 사용 → 다리소재=우드
플라스틱 → 가구 부품에 사용 → 다리소재=플라스틱
혼합 → 다리소재=혼합
패브릭/천/직물 → 소파커버/쿠션에 사용 → 소재=패브릭 (소파 전체 소재)
가죽/천연가죽/인조가죽/PU → 소파커버에 사용 → 소재=가죽
스프링/본넬스프링 → 매트리스 내부 → 매트리스종류=스프링
독립스프링/포켓스프링 → 매트리스 내부 → 매트리스종류=독립스프링
라텍스 → 매트리스 소재 → 매트리스종류=라텍스
메모리폼 → 매트리스 소재 → 매트리스종류=메모리폼
딱딱함/단단함/하드 → 매트리스/쿠션 느낌 → 매트리스강도=딱딱함
푹신함/소프트/부드러움 → 매트리스/쿠션 느낌 → 매트리스강도=푹신함
일자형/ㄷ자형/원형 → 다리 모양 → 다리형태=일자형
높은형/낮은형 → 침대 프레임 높이 → 프레임높이=높은형

핵심 규칙:
사용자 표현의 의미를 파악해서 보드 옵션값으로 정확히 매핑하세요.
위 재료 사전을 반드시 참고하세요.
보드 옵션 목록이 있으면 반드시 그 중에서 선택하세요.

가성비 규칙:
가성비/저렴한/cheap/budget 등의 표현은 가격=저가로만 변환하세요.

예시:
코너형 패브릭 소파 → 소파 | 형태=코너형 | 소재=패브릭
4인용 방수 패브릭 소파 → 소파 | 소재=패브릭 | 인원수=4인용 | 패브릭기능=방수
헤드있는 싱글 침대 → 침대 | 사이즈=싱글 | 헤드유무=헤드있음
싱글 침대 다리 스틸 → 침대 | 사이즈=싱글 | 다리소재=스틸
퀸 침대 다리 스틸 매트리스 딱딱한걸로 → 침대 | 사이즈=퀸 | 다리소재=스틸 | 매트리스강도=딱딱함

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


def _apply_vs_checked(board_text, checked):
    """VS에서 수집된 값들을 상황판에 CHECKED로 반영"""
    for key, val in checked.items():
        if key == '소재':
            continue  # context로 이미 처리
        # 옵션에 CHECKED 표시
        import re
        board_text = re.sub(
            rf'\b{re.escape(val)}\b(?! CHECKED)',
            f'{val} CHECKED:{val}',
            board_text
        )
        print(f'[VS CHECKED] {key}={val}')
    return board_text


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

    # 가구 대분류 → 카테고리 선택
    if zone == 'furniture_category':
        items = route_result.get('items', [])
        session_brand = route_result.get('brand', '')
        if session and session_brand:
            session['furniture_brand'] = session_brand
        return {
            'type': 'context_select',
            'text': 'CONTEXT_SELECT:' + '/'.join(items)
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
def make_summary(product_name, selections, raw_product, constraint_keys=None, product_type=None, context=None):
    """선택값을 자연스러운 문장으로 요약 + 제약 안내 포함"""

    # 특수 제품 유형 + context 반영
    type_parts = []
    # 원목은 기본값이라 제외, 나머지 context는 모두 요약에 포함
    if context and context not in ['원목', '']:
        type_parts.append(context)
    if product_type:
        type_parts.append(product_type)
    type_hint = f'\n※ 소재/유형: {", ".join(type_parts)} (반드시 요약에 포함)' if type_parts else ''

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
            constraint_notice = call_llm(notice_prompt, max_tokens=400).strip()

    prompt = f"""고객이 찾는 제품 조건을 자연스럽고 따뜻한 한 문장으로 요약하세요.
반드시 아래 형식으로만 출력하세요.

제품: {raw_product}
선택조건: {selections}{type_hint}

형식:
쇼핑 검색 조건이 완성됐어요 고객님! 🛍️
[조건을 자연스러운 한 문장으로 요약 + 이모지]
이 조건으로 제품을 찾아볼까요?

예시출력:
쇼핑 검색 조건이 완성됐어요 고객님! 🛍️
우드슬랩 오크 원목으로 만든 6인용 식탁을 찾으시는군요 🪵
이 조건으로 제품을 찾아볼까요?"""
    summary = call_llm(prompt, max_tokens=150).strip()
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
        constraint_notice = call_llm(notice_prompt, max_tokens=400).strip()

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


def add_dynamic_options(board_text: str, extra_text: str, product: str, skip_categories: set = None) -> str:
    """
    상황판에 없는 조건 → LLM이 카테고리+옵션 생성
    코드가 판단: 이미 있으면 스킵, 없으면 추가
    """
    if not extra_text or not board_text:
        return board_text

    existing_labels = re.findall(r'\[([^\]]+)\]', board_text)
    existing_labels_str = ', '.join(existing_labels)
    skip_categories = skip_categories or set()

    # 1단계: 상황판 기존 옵션에서 pre-check 가능한 것 먼저 처리
    OPTION_ALIAS = {
        '라운드': ('형태', '원형'),
        '원형': ('형태', '원형'),
        '직사각': ('형태', '직사각형'),
        '확장': ('형태', '확장형'),
        '유광': ('마감', '유광'),
        '무광': ('마감', '무광'),
        '스틸': ('프레임', '스틸'),
        '원목': ('프레임', '원목'),
        '밝은': ('색상', '밝은톤'),
        '어두운': ('색상', '어두운톤'),
        '화이트': ('색상', '밝은톤'),
        '블랙': ('색상', '어두운톤'),
        '2인용': ('인원수', '2인용'),
        '4인용': ('인원수', '4인용'),
        '6인용': ('인원수', '6인용'),
        '모듈형': ('형태', '모듈형'),
        '일반형': ('형태', '일반형'),
        '붙박이': ('형태', '붙박이형'),
        '직선형': ('형태', '직선형'),
        '코너형': ('형태', '코너형'),
        '카우치': ('형태', '카우치형'),
        '매트리스': ('매트리스', '포함'),
    }

    # 1단계: OPTION_ALIAS로 pre-check 또는 작은 옵션 추가
    alias_handled = False
    for kw, (label, value) in OPTION_ALIAS.items():
        if kw not in extra_text:
            continue
        if f'[{label}]' not in board_text:
            continue

        # 케이스 1: 큰 옵션 있고 작은 옵션도 있음 → CHECKED만
        if value in board_text:
            # 이미 CHECKED 됐으면 스킵
            if f'CHECKED:{value}' in board_text:
                alias_handled = True
                break
            board_text = re.sub(
                rf'(\b{re.escape(value)}\b)(?! CHECKED)',
                f'{value} CHECKED:{value}',
                board_text,
                count=1
            )
            print(f'[동적pre-check] {label}={value} CHECKED')
            alias_handled = True

        # 케이스 2: 큰 옵션은 있는데 작은 옵션(value)이 없음 → 추가 + CHECKED
        else:
            lines = board_text.split('\n')
            for i, line in enumerate(lines):
                if line.strip() == f'[{label}]' and i + 1 < len(lines):
                    lines[i + 1] = lines[i + 1] + f' / {value} CHECKED:{value}'
                    board_text = '\n'.join(lines)
                    print(f'[동적옵션추가] {label}에 {value} 추가 + CHECKED')
                    alias_handled = True
                    break
        if alias_handled:
            break

    # OPTION_ALIAS에서 처리됐어도 강도/세부속성이면 LLM도 실행
    if alias_handled:
        # 강도/세부속성 관련이면 LLM도 실행 (매트리스강도, 다리형태 등)
        DETAIL_KEYWORDS = ['딱딱', '푹신', '단단', '부드러', '강도', '형태']
        if not any(kw in extra_text for kw in DETAIL_KEYWORDS):
            return board_text

    # 2단계: LLM에게 카테고리명+옵션만 물어보고, 판단은 코드가
    SKIP_KEYWORDS = ['어떻게', '방법', '지우', '닦', '관리', '세척', '청소',
                     '강하나', '튼튼', '얼마나', '오래']
    if any(kw in extra_text for kw in SKIP_KEYWORDS):
        print(f'[동적옵션 스킵] 정보성 질문: {extra_text[:30]}')
        return board_text

    # LLM: 카테고리명과 옵션목록만 생성 (판단X)
    prompt = f"""제품={product}
조건="{extra_text}"

이 조건의 카테고리명과 옵션목록을 아래 형식으로만 출력:
카테고리명|선택값|옵션1,옵션2,옵션3

예시:
"딱딱한걸로" -> 매트리스강도|딱딱함|딱딱함,적당함,푹신함
"스프링으로" -> 매트리스종류|스프링|스프링,라텍스,메모리폼,독립스프링
"스틸 다리" -> 다리소재|스틸|스틸,우드,혼합
"모듈형으로" -> 형태|모듈형|일반형,붙박이형,모듈형

설명금지. 형식만출력."""

    result = call_llm(prompt, max_tokens=60).strip()
    print(f'[동적옵션LLM] extra="{extra_text[:20]}" -> {result[:60]}')

    if not result or '|' not in result:
        return board_text

    # 첫 번째 유효한 줄만 처리 (조건 하나씩 호출하므로)
    first_line = result.split('\n')[0].strip()
    parts = first_line.split('|')
    if len(parts) < 3:
        return board_text

    category = parts[0].strip()
    checked_val = parts[1].strip()
    options = [o.strip() for o in parts[2].split(',') if o.strip()]

    if not category or not options:
        return board_text

    # 사이즈/크기 관련 카테고리 스킵
    if category in skip_categories or any(kw in category for kw in ['크기', '사이즈', '규격']):
        print(f'[동적옵션 스킵] 사이즈 카테고리: [{category}]')
        return board_text

    # 코드가 판단: 상황판에 이미 있으면 스킵
    if f'[{category}]' in board_text:
        print(f'[동적옵션 스킵] [{category}] 이미 상황판에 있음')
        return board_text

    # 없으면 추가
    opts_str = ' / '.join(
        f'{o} CHECKED:{o}' if o == checked_val else o
        for o in options
    )
    new_section = f'[{category}]\n{opts_str}'
    print(f'[동적옵션추가] [{category}] {checked_val} CHECKED')

    if '[E 직접입력]' in board_text:
        return board_text.replace('[E 직접입력]', new_section + '\n\n[E 직접입력]')
    return board_text + '\n\n' + new_section


def _search_worry_info(worry_text: str, product_name: str, mentioned_items: list = None) -> str:
    """사용자 걱정/질문으로 웹 검색해서 근거 있는 정보 반환"""

    # LLM이 검색 쿼리 생성 (하드코딩 없음)
    # 시간에 따라 변하는 정보 → 웹검색
    # 변하지 않는 일반 지식 → LLM 직접
    mentioned_str = f'\n이미 언급된 항목: {", ".join(mentioned_items)}' if mentioned_items else ''
    search_prompt = f"""제품: {product_name}
사용자 질문: "{worry_text}"{mentioned_str}

판단:
1. 최신 가격/재고/브랜드/트렌드 → 웹검색 필요
2. 소재특징/관리법/종류/차이점 → 웹검색 필요
3. 단순 선호도/감정 → NONE
4. 이미 언급된 항목만 묻는 것 → NONE

웹검색 필요하면: 검색쿼리 한 줄만 출력 (한국어, 구체적, 이미 언급된 항목 제외)
불필요하면: NONE"""

    query = call_llm(search_prompt, max_tokens=60).strip()
    if not query or 'NONE' in query:
        return ''

    print(f'[웹검색] 쿼리: {query}')

    try:
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01'
        }
        body = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 500,
            'tools': [{'type': 'web_search_20250305', 'name': 'web_search'}],
            'system': '검색 결과를 간결하게 3~4줄로 요약하세요. 한국어로.',
            'messages': [{'role': 'user', 'content': query}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body, headers=headers, method='POST'
        )
        res = urllib.request.urlopen(req, timeout=8)
        data = json.loads(res.read())

        # domain → 한국어 사이트명 매핑
        DOMAIN_NAMES = {
            'mypetlife.co.kr': '비마이펫',
            'woowarhanclean.com': '우아한정리',
            'naver.com': '네이버',
            'blog.naver.com': '네이버 블로그',
            'coupang.com': '쿠팡',
            'ohou.se': '오늘의집',
            'ikea.com': '이케아',
            'samsung.com': '삼성',
            'lg.com': 'LG',
            '11st.co.kr': '11번가',
            'gmarket.co.kr': 'G마켓',
            'auction.co.kr': '옥션',
            'zigzag.kr': '지그재그',
            'musinsa.com': '무신사',
            'apure.kr': '에이퓨어',
            'brunch.co.kr': '브런치',
        }

        # 텍스트 + 출처 URL 추출
        texts = []
        sources = []  # {name, url} 딕셔너리 리스트
        for block in data.get('content', []):
            if block.get('type') == 'text':
                texts.append(block['text'])
                for citation in block.get('citations', []):
                    url = citation.get('url', '')
                    if url and url.startswith('http'):
                        try:
                            domain = url.split('/')[2]
                            domain = domain.replace('www.', '')
                            if any(s['domain'] == domain for s in sources):
                                continue
                            # 알려진 도메인이면 한국어명, 모르면 도메인에서 추출
                            if domain in DOMAIN_NAMES:
                                name = DOMAIN_NAMES[domain]
                            else:
                                # 도메인에서 사이트명 자동 추출
                                parts = domain.split('.')
                                raw_name = parts[0] if parts[0] not in ['m', 'www', 'blog', 'store', 'shop', 'post'] else parts[1] if len(parts) > 1 else domain
                                # 너무 길거나 의미없는 이름 → 도메인 축약
                                if len(raw_name) > 12:
                                    raw_name = raw_name[:10] + '...'
                                name = raw_name
                            sources.append({'name': name, 'url': url, 'domain': domain})
                        except:
                            pass

        result = ' '.join(texts).strip()

        # 출처 붙이기 - LINK 형식으로 (app.js에서 파싱)
        if sources:
            source_str = '|'.join([f"{s['name']}::{s['url']}" for s in sources[:2]])
            result += f'\n\n📌SOURCE::{source_str}'
        else:
            result += '\n\n📌SOURCE::웹검색기반::https://www.google.com'

        print(f'[웹검색 결과] {result[:80]}...')
        return result
    except Exception as e:
        print(f'[웹검색 오류] {e}')
        return ''


def _extract_worry_selected(worry_text: str, product: str) -> dict:
    """사용자 걱정 키워드 → 상황판 selected 자동 매핑"""
    selected = {}
    t = worry_text.lower()

    # 반려동물 → 스크래치방지 + 오염방지 + 커버세탁 모두 체크
    if any(k in t for k in ['강아지', '고양이', '반려', '애완', '펫', '털']):
        selected['패브릭기능'] = '스크래치방지'
        selected['커버세탁'] = '가능'

    # 오염/얼룩 → 오염방지 + 커버세탁
    if any(k in t for k in ['오염', '얼룩', '더러', '음식', '먹다']):
        selected['패브릭기능'] = '오염방지'
        selected['커버세탁'] = '가능'

    # 방수/물
    if any(k in t for k in ['방수', '물', '젖', '음료']):
        selected['패브릭기능'] = '방수'
        selected['커버세탁'] = '가능'

    # 세탁/청소
    if any(k in t for k in ['세탁', '청소', '빨']):
        selected['커버세탁'] = '가능'

    # 침대/매트리스
    if any(k in t for k in ['허리', '척추', '단단', '딱딱']):
        selected['쿠션감'] = '단단함'
    if any(k in t for k in ['푹신', '부드럽', '편안']):
        selected['쿠션감'] = '푹신함'

    # 의자
    if any(k in t for k in ['허리', '척추', '장시간', '오래']):
        selected['소재'] = '메쉬'

    print(f'[걱정매핑] "{worry_text}" → {selected}')
    return selected


# ===============================
# Decision Engine 메인
# ===============================
def decision_engine(user_input, session=None):
    session  = _init_session(session)

    # ADD_ITEM은 ocr_layer 전에 먼저 처리 (콜론 제거 방지)
    if isinstance(user_input, str) and user_input.startswith('ADD_ITEM:') and session.get('stage') == 'anti_confirm':
        raw_text = user_input
        parts = raw_text.split(':')
        if len(parts) >= 4:
            group_name = parts[1]
            selected_item = parts[2]
            all_items = parts[3].split(',')
        elif len(parts) >= 3:
            group_name = parts[1]
            all_items = parts[2].split(',')
            selected_item = all_items[0]
        else:
            return "추가됐어요! 😊"

        board_product = session.get('raw_product', '')
        board_result = make_board(board_product, session)
        board_text = board_result.get('text', '')
        opts_str = ' / '.join(
            f'{o} CHECKED:{o}' if o == selected_item else o
            for o in all_items
        )
        new_section = f'[{group_name}]\n{opts_str}'
        if f'[{group_name}]' not in board_text and '[E 직접입력]' in board_text:
            board_text = board_text.replace('[E 직접입력]', new_section + '\n\n[E 직접입력]')

        # session에 추가 항목 저장 (네, 찾아주세요 클릭 시 유지)
        extra_sections = session.get('extra_board_sections', {})
        extra_sections[group_name] = opts_str
        session['extra_board_sections'] = extra_sections

        session['stage'] = 'anti_confirm'
        print(f'[아이템추가] [{group_name}] {selected_item} CHECKED')
        return f'BOARD_UPDATE\n\n{board_text}'

    ocr      = ocr_layer(user_input)
    if ocr['empty']:
        return "무엇을 찾고 계신가요? 😊"
    raw_text = ocr['clean']
    original_text = raw_text  # 원문 보존 (공감멘트용)
    stage    = session.get('stage')

    # ── 1단계 최초 입력만 정규화 (context_wait 등은 제외) ──
    if not stage:
        raw_text = normalize_query(raw_text)

        # selected 교정: 인원수가 다른 키로 잘못 분류된 경우 수정
        selected = getattr(normalize_query, '_selected', {})
        PERSON_KEYWORDS = {'1인용','2인용','3인용','4인용','5인용','6인용','6인용이상'}
        SHAPE_KEYWORDS = {'모듈형','일반형','붙박이형','직선형','코너형','카우치형','원형','직사각형','확장형'}

        # 원문에서 형태 키워드 직접 감지
        SHAPE_IN_TEXT = {
            '모듈형': '모듈형', '모듈': '모듈형',
            '직선형': '직선형', '직선': '직선형',
            '코너형': '코너형', '코너': '코너형',
            '카우치형': '카우치형', '카우치': '카우치형',
            '붙박이형': '붙박이형', '붙박이': '붙박이형',
        }

        # 매트리스 강도/종류 키워드 → dynamic_extra로 별도 처리
        MATTRESS_IN_TEXT = {
            '딱딱': '딱딱한 매트리스',
            '단단': '딱딱한 매트리스',
            '푹신': '푹신한 매트리스',
            '부드러': '푹신한 매트리스',
            '스프링': '스프링 매트리스',
            '라텍스': '라텍스 매트리스',
            '메모리폼': '메모리폼 매트리스',
            '독립스프링': '독립스프링 매트리스',
        }

        corrected = dict(selected)
        # 원문에서 형태 키워드 직접 찾기 (LLM 오분류 우선 교정)
        SHAPE_BOARD_OPTIONS = {'직선형','코너형','카우치형','원형','직사각형','확장형','붙박이형','일반형'}
        for kw, shape_val in SHAPE_IN_TEXT.items():
            if kw in original_text:
                if shape_val in SHAPE_BOARD_OPTIONS:
                    corrected['형태'] = shape_val
                    print(f'[selected교정] 원문에서 {kw} 감지 → 형태={shape_val}')
                else:
                    corrected['dynamic_extra'] = shape_val
                    # 잘못 분류된 형태 키 제거 (라우터가 엉뚱한 CHECKED 못 붙이게)
                    if '형태' in corrected:
                        del corrected['형태']
                    print(f'[selected교정] 원문에서 {kw} 감지 → dynamic_extra={shape_val}')
                break

        for k, v in selected.items():
            if v in PERSON_KEYWORDS and k != '인원수':
                corrected['인원수'] = v
                if k in corrected and k != '인원수':
                    del corrected[k]
                print(f'[selected교정] {k}={v} → 인원수={v}')

        # 매트리스 강도 키워드 감지 → dynamic_extra
        for kw, mat_val in MATTRESS_IN_TEXT.items():
            if kw in original_text:
                corrected['dynamic_extra'] = mat_val
                # 잘못 분류된 매트리스종류 키 제거
                if '매트리스종류' in corrected:
                    del corrected['매트리스종류']
                print(f'[selected교정] 매트리스강도 감지 → dynamic_extra={mat_val}')
                break

        normalize_query._selected = corrected

    # ── 멀티 제품 감지 → MULTI_SELECT ──
    if not stage:
        # 소파 침대 애매한 경우 → 선택지 제공
        if getattr(normalize_query, '_sofa_bed_select', False):
            return "소파와 침대, 어떤 걸 찾으세요? 😊\n\nCONTEXT_SELECT:소파/침대/소파베드"
        multi = getattr(normalize_query, '_multi_products', [])
        print(f'[멀티감지] raw={raw_text} multi={multi}')
        if multi:
            # VS 먼저 체크! (살까 2개 = VS, 멀티 아님)
            vs_check = detect_vs(original_text)
            if vs_check:
                pass  # VS로 처리 (아래 VS 감지에서 처리)
            else:
                session['multi_queue'] = multi[1:]
                session['stage'] = 'multi_wait'
                products_str = '/'.join(multi)
                count = len(multi)
                if count == 2:
                    msg = "두 가지 제품을 선택하셨네요! 하나씩 찾아볼까요? 😊"
                elif count == 3:
                    msg = "세 가지 제품을 선택하셨네요! 하나씩 찾아볼까요? 😊"
                else:
                    msg = f"{count}가지 제품을 선택하셨네요! 하나씩 찾아볼까요? 😊"
                return f"{msg}\n\nMULTI_SELECT:{products_str}"

    # ── 반의도 확인 버튼 처리 ──
    if stage == 'anti_confirm':
        print(f'[anti_confirm] raw_text={raw_text}')

        # 아이템 상황판 추가 버튼 클릭
        if raw_text.startswith('ADD_ITEM:'):
            # ADD_ITEM:원목종류:선택값:오크,월넛
            parts = raw_text.split(':')
            if len(parts) >= 4:
                group_name = parts[1]
                selected_item = parts[2]  # 클릭한 값
                all_items = parts[3].split(',')  # 전체 옵션
            elif len(parts) >= 3:
                group_name = parts[1]
                all_items = parts[2].split(',')
                selected_item = all_items[0]
            else:
                return "추가됐어요! 😊"

            board_product = session.get('raw_product', '')
            board_result = make_board(board_product, session)
            board_text = board_result.get('text', '')
            # 클릭한 값만 CHECKED
            opts_str = ' / '.join(
                f'{o} CHECKED:{o}' if o == selected_item else o
                for o in all_items
            )
            new_section = f'[{group_name}]\n{opts_str}'
            if f'[{group_name}]' not in board_text and '[E 직접입력]' in board_text:
                board_text = board_text.replace('[E 직접입력]', new_section + '\n\n[E 직접입력]')
            session['stage'] = 'board_shown'
            print(f'[아이템추가] [{group_name}] {selected_item} CHECKED')
            return board_text

        # 네 → 상황판 직행
        if any(w in raw_text for w in ['네, 찾아주세요', '네 찾아주세요', '찾아주세요']):
            board_product = session.get('raw_product', raw_text)
            board_result = make_board(board_product, session)
            board_text = board_result.get('text', '')

            # context_select가 나오면 context_wait로 전환 (상황판 선택 단계)
            if board_result.get('type') == 'context_select':
                session['stage'] = 'context_wait'
                return board_text

            # product_type이 현재 context와 맞지 않으면 초기화
            product_type = session.get('product_type')
            context = session.get('context', '')
            if product_type and context:
                type_check_prompt = f'"{product_type}"은 "{context}" 카테고리에 속하나요? 예/아니요만'
                check = call_llm(type_check_prompt, max_tokens=5).strip()
                if '아니' in check:
                    print(f'[product_type 초기화] {product_type} ≠ {context}')
                    session['product_type'] = None
            # 저장된 추가 항목 복원
            extra_sections = session.get('extra_board_sections', {})
            for group_name, opts_str in extra_sections.items():
                if f'[{group_name}]' not in board_text and '[E 직접입력]' in board_text:
                    new_section = f'[{group_name}]\n{opts_str}'
                    board_text = board_text.replace('[E 직접입력]', new_section + '\n\n[E 직접입력]')
            session['stage'] = 'board_shown'
            session['extra_board_sections'] = {}
            return board_text
        # 더 물어볼게요 → anti_dialog로 복귀
        if any(w in raw_text for w in ['더 물어볼게요', '더 물어', '궁금한게']):
            session['stage'] = 'anti_dialog'
            session['anti_turns'] = 0
            import random
            MORE_MSGS = [
                "어떤 부분이 아직 걱정되세요? 😊",
                "또 궁금한 점이 있으신가요? 😊",
                "더 알고 싶은 게 있으세요? 🤔",
                "어떤 점이 마음에 걸리세요? 😊",
                "무엇이 더 궁금하신가요? 😊",
            ]
            return random.choice(MORE_MSGS)
        # 안 살래요
        if any(w in raw_text for w in ['안 살래요', '안살래요', '안 사']):
            session['stage'] = None
            refused = session.get('refused_products', [])
            refused.append(session.get('raw_product', ''))
            session['refused_products'] = refused
            return "알겠어요! 나중에 필요하시면 언제든지 찾아주세요 😊"

        # 3버튼 아닌 새 질문 → anti_dialog로 처리
        stage = 'anti_dialog'
        session['stage'] = 'anti_dialog'
        session['anti_turns'] = 0
        # fall through to anti_dialog

    # ── 멀티 대기: 사용자가 MULTI_SELECT에서 선택 ──
    if stage == 'multi_wait':
        session['stage'] = None
        raw_text = normalize_query(raw_text)

    # ── 반의도 대화 중: 사용자 답변 → 웹 검색 → LLM 처리 → 상황판 유도 ──
    if stage == 'anti_dialog':
        print(f'[anti_dialog] raw_text={raw_text} turns={session.get("anti_turns",0)}')
        from policy_layer import get_policy, build_llm_prompt
        scores = session.get('anti_scores', {})
        policy = get_policy(scores)

        # "안 살래요" 처리
        if any(w in raw_text for w in ['안 살래요', '안살래요', '안 사', '그냥 안']):
            session['stage'] = None
            session['anti_turns'] = 0
            refused = session.get('refused_products', [])
            refused.append(session.get('raw_product', ''))
            session['refused_products'] = refused
            return "알겠어요! 나중에 필요하시면 언제든지 찾아주세요 😊"

        # "네 찾아주세요" 처리 → 상황판 직행
        if any(w in raw_text for w in ['네, 찾아주세요', '네 찾아주세요', '찾아주세요']):
            board_product = session.get('raw_product', raw_text)
            board_result = make_board(board_product, session)
            session['stage'] = 'board_shown'
            session['anti_turns'] = 0
            return board_result.get('text', '')

        # "더 물어볼게요" 처리 - stage 유지
        if any(w in raw_text for w in ['더 물어볼게요', '더 물어', '궁금한게']):
            session['stage'] = 'anti_dialog'
            session['anti_turns'] = 0
            import random
            MORE_MSGS = [
                "어떤 부분이 아직 걱정되세요? 😊",
                "또 궁금한 점이 있으신가요? 😊",
                "더 알고 싶은 게 있으세요? 🤔",
                "어떤 점이 마음에 걸리세요? 😊",
                "무엇이 더 궁금하신가요? 😊",
            ]
            return random.choice(MORE_MSGS)

        # 턴 카운트 증가
        anti_turns = session.get('anti_turns', 0) + 1
        session['anti_turns'] = anti_turns

        # 이미지 요청 감지
        IMAGE_KEYWORDS = ['이미지', '사진', '보여줘', '어떻게 생겼', '어떤 모양', '사진으로', '그림으로', '비주얼']
        if any(kw in raw_text for kw in IMAGE_KEYWORDS):
            # 검색 키워드 추출
            img_prompt = f"""사용자: "{raw_text}"
이미지 검색할 핵심 키워드만 추출하세요. (예: 패브릭소파 인테리어)
인스타그램 해시태그용으로 붙여쓰기. 키워드만 한 줄 출력."""
            img_query = call_llm(img_prompt, max_tokens=30).strip()

            # Apify 인스타그램 이미지 검색
            images = search_instagram_images(img_query, limit=3)

            if images:
                import json
                images_json = json.dumps(images, ensure_ascii=False)
                session['stage'] = 'anti_confirm'
                return f'IMAGE_RESULTS:{images_json}\n\nANTI_CONFIRM_BUTTONS\n\n{session.get("last_board_text", "")}'
            else:
                # 이미지 없으면 기존 방식
                session['stage'] = 'anti_confirm'
                return f'IMAGE_SEARCH:{img_query}\n\nANTI_CONFIRM_BUTTONS\n\n{session.get("last_board_text", "")}'

        # 걱정 키워드 + 제품명으로 검색 쿼리 생성
        board_product = session.get('raw_product', raw_text)
        # product_name: "4인용 패브릭 소파" → "소파" (마지막 명사)
        try:
            r = _route(board_product)
            product_name = r.get('product', board_product.split()[-1] if board_product else '')
        except:
            product_name = board_product.split()[-1] if board_product else ''

        # 이미 언급된 아이템 목록 (맥락 전달)
        mentioned_items = []
        for group_items in session.get('extra_board_sections', {}).values():
            # "오크 CHECKED:오크 / 월넛" → ['오크', '월넛']
            items = [i.split(' CHECKED')[0].strip() for i in group_items.split(' / ')]
            mentioned_items.extend(items)

        # 웹 검색으로 근거 있는 정보 수집
        search_result = _search_worry_info(raw_text, product_name, mentioned_items or None)

        # 출처 별도 저장 (LLM이 버리므로 직접 붙임)
        search_source = ''
        if search_result and '📌SOURCE::' in search_result:
            parts = search_result.split('\n\n📌SOURCE::')
            search_result_clean = parts[0]
            search_source = '📌SOURCE::' + parts[1] if len(parts) > 1 else ''
        else:
            search_result_clean = search_result

        # 검색 결과 포함한 프롬프트 구성
        search_context = ''
        if search_result_clean:
            search_context = f"""
[검색 결과 - 반드시 이 정보를 기반으로 답변하세요]
{search_result_clean}
"""

        anti_rule = policy['rule'] + f"""
{search_context}
[맥락 유지 - 절대 규칙]
사용자가 찾는 제품: {product_name}
이 제품에 대한 대화입니다. 다른 제품으로 절대 바꾸지 마세요.
예: "패브릭 소파" → 소파에 대해서만 답변
    "패브릭 가방" 같은 엉뚱한 제품 절대 금지

[답변 규칙]
- 반드시 {product_name} 에 대한 답변만
- 검색 결과가 있으면 그 내용 기반으로 답변
- 검색 결과 없으면 일반 지식으로 답변 (추측 금지)
- 2~3줄로 간결하게
- 마지막: "그럼 조건 골라볼까요? 😊"
- 마지막 줄에 BOARD_READY 출력
"""
        prompt = build_llm_prompt(raw_text, scores, {**policy, 'rule': anti_rule})

        ANTI_SYSTEM_RULES = """
당신은 친절한 쇼핑 상담 AI입니다.
사용자의 걱정을 공감하고 해소해주세요.

[절대 금지]
- [A ...] [B ...] [C ...] 형식 상황판 출력 금지
- 상황판 형식 절대 출력 금지
- 3줄 이상 답변 금지
- BOARD_READY 빼고 다른 특수 키워드 금지

[반드시]
- 2~3줄로 간결하게 답변
- 마지막 줄에 반드시 BOARD_READY 출력
"""
        response = call_llm(prompt, system=ANTI_SYSTEM_RULES, max_tokens=200)

        # BOARD_READY 감지 → 상황판 출력
        if 'BOARD_READY' in response:
            response = response.replace('BOARD_READY', '').strip()
        else:
            # BOARD_READY 없어도 강제로 상황판 전환 (LLM이 안 붙인 경우)
            pass

        # 항상 상황판으로 전환
        session['anti_turns'] = 0
        worry_selected = _extract_worry_selected(raw_text, board_product)
        if worry_selected:
            existing = getattr(normalize_query, '_selected', {})
            existing.update(worry_selected)
            normalize_query._selected = existing

        # board_product를 정규화된 제품명으로 정확히 추출
        raw_product = session.get('raw_product', '')
        if raw_product:
            try:
                r = _route(raw_product)
                clean_product = r.get('product', '')
                if clean_product and len(clean_product) < 20:
                    board_product = raw_product  # 원문으로 make_board 호출
            except:
                pass

        board_result = make_board(board_product, session)
        board_text = board_result.get('text', '')

        # LLM 폴백 상황판 감지 → board_llm으로 올바른 형식으로 대체
        is_fallback = (
            '[A ' in board_text or
            '[B ' in board_text or
            '조건을 선택해주세요' not in board_text
        )
        if is_fallback:
            print(f'[폴백차단] board_llm으로 대체 생성')
            try:
                from situation_layer.boards.board_llm import get_board as llm_board
                board_text = llm_board(product=product_name)
                # board_llm도 실패하면 빈 텍스트
                if not board_text or '조건을 선택해주세요' not in board_text:
                    board_text = f'조건을 선택해주세요\n\n[E 직접입력]\n원하는 조건을 직접 입력하세요'
            except Exception as e:
                print(f'[board_llm 오류] {e}')
                board_text = f'조건을 선택해주세요\n\n[E 직접입력]\n원하는 조건을 직접 입력하세요'

        # 동적 옵션 추가
        if any(k in raw_text for k in ['컬러', '색상', '다리', '소재', '크기', '디자인', '형태', '원목', '종류']):
            board_text = add_dynamic_options(board_text, raw_text, product_name)

        # 소재/카테고리 변경 감지 → session context 업데이트
        CONTEXT_CHANGE_MAP = {
            '세라믹': '세라믹', '세라믹으로': '세라믹',
            '원목으로': '원목', '원목 식탁': '원목',
            '대리석으로': '대리석', '대리석 식탁': '대리석',
            '패브릭으로': '패브릭', '가죽으로': '가죽',
            '스틸로': '스틸', '철재로': '스틸',
        }
        for kw, new_ctx in CONTEXT_CHANGE_MAP.items():
            if kw in raw_text:
                old_ctx = session.get('context', '')
                if old_ctx != new_ctx:
                    print(f'[소재변경감지] {old_ctx} → {new_ctx}')
                    session['context'] = new_ctx
                    session['product_type'] = None
                    session['extra_board_sections'] = {}
                    # board_text 새로 생성
                    try:
                        new_board = _get_new_board(product_name, context=new_ctx)
                        if new_board and not new_board.startswith('CONTEXT_SELECT:'):
                            board_text = new_board
                    except:
                        pass
                break

        # 특수 제품 유형 감지 → session에 저장 (최종 요약에 반영)
        PRODUCT_TYPE_KEYWORDS = {
            '우드슬랩': '우드슬랩', '우드 슬랩': '우드슬랩',
            '통원목': '통원목', '솔리드우드': '통원목',
            '집성목': '집성목', '집성': '집성목',
            '무늬목': '무늬목',
            '메모리폼': '메모리폼',
            '라텍스': '라텍스',
            '모듈형': '모듈형',
            '붙박이': '붙박이형',
        }
        for kw, ptype in PRODUCT_TYPE_KEYWORDS.items():
            if kw in raw_text or kw in response:
                session['product_type'] = ptype
                print(f'[제품유형감지] {ptype}')
                break

        # LLM 답변에서 구체적 아이템 감지 → 버튼으로 상황판 추가 제안
        ITEM_GROUPS = {
            '원목종류': ['참나무', '오크', '월넛', '소나무', '자작나무', '티크', '애쉬', '체리', '메이플', '고무나무', '너도밤나무', '멀바우'],
            '패브릭종류': ['린넨', '벨벳', '마이크로화이버', '코듀로이', '폴리에스터'],
            '매트리스종류': ['라텍스', '메모리폼', '스프링', '독립스프링', '하이브리드'],
            '색상종류': ['화이트', '블랙', '그레이', '베이지', '브라운', '네이비'],
        }

        item_select_str = ''
        for group_name, items in ITEM_GROUPS.items():
            mentioned = [item for item in items if item in response]
            if len(mentioned) >= 2:  # 2개 이상 언급됐을 때만 버튼 제안
                item_select_str = f'ITEM_SELECT:{group_name}:{",".join(mentioned)}'
                print(f'[아이템선택버튼] {group_name}: {mentioned}')
                break

        session['stage'] = 'anti_confirm'
        session['last_board_text'] = board_text  # 이미지 요청 시 재사용
        clean_response = response.replace('BOARD_READY', '').strip()
        if search_source:
            clean_response += f'\n\n{search_source}'
        if item_select_str:
            clean_response += f'\n\n{item_select_str}'
        return clean_response + '\n\nANTI_CONFIRM_BUTTONS\n\n' + board_text

    # ── Context 대기: 가정/사무실/업소 선택 → 상황판 진입 ──
    if stage == 'context_wait':
        # context 누적 (어린이→단행본→팝업북 순서 추적)
        prev_context = session.get('context', '')
        session['context'] = raw_text

        # 큰 카테고리 변경 → 이전 세부정보 초기화 (범용)
        # 예: 원목 대화 중 세라믹 선택 → product_type, extra_board_sections 리셋
        if prev_context and prev_context != raw_text:
            print(f'[카테고리변경] {prev_context} → {raw_text} / 세부정보 초기화')
            session['product_type'] = None
            session['extra_board_sections'] = {}
            session['mentioned_items'] = []

        if _NEW_ROUTER_ENABLED:
            try:
                # 원래 product 정제
                raw_product = session.get('raw_product', raw_text)
                r = _route(raw_product)
                clean_product = r.get('product', raw_product)

                print(f'[context_wait] clean_product={clean_product} raw_text={raw_text} prev={prev_context}')

                # VS에서 소재 선택한 경우 → choice로 전달 (소재 선택 단계 스킵!)
                vs_material = session.get('vs_material', '')
                auto_selected = session.get('auto_selected', {})
                choice = vs_material if vs_material else auto_selected
                board_text = _get_new_board(clean_product, context=raw_text, choice=choice)
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

    # ── VS 결과에서 사용자가 소파 선택 → 상황판 진입 ──
    # ── VS 선택: 사용자가 카드 보고 제품 선택 → 기존 상황판 흐름 ──
    if stage == 'vs_cards' and raw_text.startswith('VS_SELECT:'):
        selected_product = raw_text.replace('VS_SELECT:', '').strip()
        print(f'[VS선택] product={selected_product}')

        board_product = session.get('raw_product', '소파')

        # 정규화로 소재/인원수 추출
        normalize_query(selected_product)
        norm_selected = getattr(normalize_query, '_selected', {})
        print(f'[VS정규화] {selected_product} → {norm_selected}')

        # 소재/인원수 session에 저장
        vs_material = norm_selected.get('소재', '')
        vs_size = norm_selected.get('인원수', '')

        if vs_material:
            session['vs_material'] = vs_material  # 소재 별도 보관
        if vs_size:
            session['context'] = vs_size  # 인원수 있으면 context로

        # 기존 살까말까 상황판 흐름
        board_result = make_board(board_product, session)
        board_text = board_result.get('text', '')

        # context_select (인원수) 나오면 → context_wait
        if board_result.get('type') == 'context_select':
            session['stage'] = 'context_wait'
            return board_text

        session['stage'] = 'board_shown'
        return board_text

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
            remaining = len(queue)
            if remaining > 0:
                msg = f"다음은 {next_product} 찾아볼까요? 아직 {remaining}개 더 남았어요 😊"
            else:
                msg = f"마지막으로 {next_product}도 찾아드릴게요! 😊"
            return f"{msg}\n\nMULTI_SELECT:{next_product}"

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
            constraint_keys=all_keys,
            product_type=session.get('product_type'),
            context=session.get('context', '')
        )
        session['summary'] = summary

        # 확인 버튼 3개 포함
        return f"{summary}\n\nCONFIRM_BUTTONS"

    # ── 1단계: 처음 입력 → VS 체크 먼저 → 센서 → 반의도 체크 → 상황판 ──

    product = classify_product(original_text)

    # dynamic_extra 저장 (make_board 전에 읽어두고, 라우터엔 전달 안함)
    _sel_now = getattr(normalize_query, '_selected', {})
    _dynamic_extra = _sel_now.get('dynamic_extra', None)
    # 라우터가 엉뚱한 CHECKED 못 붙이게 제거
    if 'dynamic_extra' in _sel_now:
        del _sel_now['dynamic_extra']
    normalize_query._selected = _sel_now

    # VS 사전 감지 먼저 (센서보다 우선!)
    board_precheck = make_board(raw_text, session)
    is_vs = board_precheck.get('type') == 'vs_explain'

    if not product['is_product'] and not is_vs:
        return get_out_of_scope_message()

    # VS면 바로 VS 모드로
    if is_vs:
        session['stage'] = 'vs_wait'
        session['vs_options'] = board_precheck.get('vs_options', [])
        vs_options_str = '/'.join(board_precheck.get('vs_options', []))
        vs_text = board_precheck['text']
        vs_text += f"\n\nVS_SELECT:{vs_options_str}"
        # VS는 LLM 공감멘트 자유롭게
        import random
        drive = {}
        empathy = call_llm(f"""
사용자가 "{original_text}" 라고 입력했어요.
두 가지를 비교하며 고민하고 있어요.
딱 한 줄만 출력하세요. 비교 상황에 맞는 따뜻한 공감 + 이모지.
질문 금지.
""", max_tokens=80).strip()
        return empathy + "\n\n" + vs_text

    # 센서 실행 (VS 아닌 경우만)
    scores = sensor_layer(original_text, session)

    # S2 패턴 보정
    if re.search(r'(찾아줘|추천|사고싶|필요해|구매)', original_text):
        scores['S_type'] = 'S2'
        if scores['I_hat'] < 0.5:
            scores['I_hat'] = 0.5
            scores['activated'] = True

    As = scores.get('As', 0)
    anti_type = scores.get('anti_type', '')
    print(f'[센서] As={As} anti_type={anti_type} S={scores.get("S_type")}')

    # ── VS 감지 → vs_cards (센서 체크 전에!) ──
    if not stage:
        vs_scenario = detect_vs(original_text)
        if vs_scenario:
            print(f'[VS감지] {vs_scenario}')
            session['stage'] = 'vs_cards'
            session['vs_scenario'] = vs_scenario
            session['vs_answers'] = {}

            # raw_product 저장
            try:
                r = _route(raw_text)
                session['raw_product'] = r.get('product', original_text)
            except:
                session['raw_product'] = original_text

            # 카드 생성 후 반환
            first_q = get_vs_first_question(vs_scenario)
            return first_q if first_q else "VS 모드를 시작할게요! 😊"

    # ── 반의도 감지 → anti_dialog (상황판 전에 체크!) ──
    # 이미 anti_dialog stage면 스킵 (위에서 처리됨)
    if As >= 0.45 and anti_type == 'ANTI_INTENT' and not stage:
        from policy_layer import get_policy, build_llm_prompt
        policy = get_policy(scores)
        if policy['action'] in ['ANTI_HIGH', 'ANTI_INTENT']:
            session['stage'] = 'anti_dialog'
            session['anti_turns'] = 0
            # raw_product: router로 정제된 제품명 저장
            try:
                r = _route(raw_text)
                clean_product = r.get('product', '')
                session['raw_product'] = clean_product if clean_product and len(clean_product) < 20 else original_text
            except:
                session['raw_product'] = original_text
            print(f'[anti_dialog 시작] raw_product={session["raw_product"]}')
            session['anti_scores'] = scores
            # 첫 턴: 포괄적 질문 (랜덤 교차)
            import random
            FIRST_QUESTIONS = [
                "혹시 어떤 점이 가장 걱정되세요? 😊",
                "구매를 망설이시는 가장 큰 이유가 뭔가요? 😊",
                "어떤 부분에서 고민이 되시나요? 😊",
            ]
            product_q = session.get('raw_product', '') or raw_text.split()[0]
            empathy_q = f"{product_q} 구매를 고민 중이시군요! {random.choice(FIRST_QUESTIONS)}"
            return empathy_q

    # 공감 멘트
    import random
    drive = scores.get('Drive', {})

    # 특별 상황 고정 템플릿 (4가지 랜덤)
    SPECIAL_TEMPLATES = {
        '신혼': [
            "두 분의 새로운 시작을 진심으로 축하드려요! 💍 첫 보금자리를 함께 완성해드릴게요 🏡",
            "설레는 신혼집, 두 분의 취향으로 가득 채워드릴게요! 💕🏠",
            "인생 최고의 순간, 완벽한 공간으로 만들어드릴게요! 💍✨",
            "두 분이 함께할 소중한 공간, 최고의 가구로 채워드릴게요! 🏡💑",
        ],
        '결혼': [
            "결혼을 진심으로 축하드려요! 💍 새 출발에 딱 맞는 것들 찾아드릴게요 🏡",
            "인생의 새 챕터를 여는 특별한 공간, 함께 만들어드릴게요! 💕✨",
            "소중한 결혼을 축하드려요! 두 분의 첫 보금자리 완성해드릴게요 💍🏠",
            "새로운 시작을 함께할 완벽한 선택, 도와드릴게요! 💑🌸",
        ],
        '이사': [
            "설레는 새 공간의 시작이군요! 🏠 새집에 딱 맞는 것들 함께 찾아드릴게요 ✨",
            "새 출발을 응원해요! 새 공간을 완벽하게 채워드릴게요 🏡🎉",
            "이사 축하드려요! 새집을 더 특별하게 만들어드릴게요 🏠✨",
            "새로운 공간, 새로운 시작! 딱 맞는 것들 골라드릴게요 🎊🏡",
        ],
        '출산': [
            "소중한 아이의 탄생을 진심으로 축하드려요! 👶 안전하고 따뜻한 제품 찾아드릴게요 🌸",
            "새 생명과 함께할 특별한 공간, 안전하게 준비해드릴게요! 👶💕",
            "아이와 함께하는 첫 공간, 완벽하게 만들어드릴게요! 🍼🌿",
            "출산 축하드려요! 소중한 아이를 위한 최선을 찾아드릴게요 👶✨",
        ],
        '아기': [
            "소중한 아이를 위한 안전하고 따뜻한 제품 찾아드릴게요! 👶🌸",
            "우리 아이에게 딱 맞는 것들, 꼼꼼하게 골라드릴게요! 👶💕",
            "아이의 안전과 편안함을 최우선으로 찾아드릴게요! 🍼✨",
            "사랑스러운 아이를 위한 최고의 선택, 함께해요! 👶🌿",
        ],
    }

    # 키워드 → 템플릿 매핑
    SPECIAL_KEYWORD_MAP = {
        # 신혼
        '신혼': '신혼', '혼수': '신혼', '새신랑': '신혼', '새신부': '신혼',
        '신혼집': '신혼', '신혼부부': '신혼',
        # 결혼
        '결혼': '결혼', '웨딩': '결혼', '예비부부': '결혼', '결혼식': '결혼',
        # 이사
        '이사': '이사', '새집': '이사', '새 집': '이사', '입주': '이사',
        '분양': '이사', '전세': '이사', '이사가': '이사', '이사해': '이사',
        # 출산/아기
        '출산': '출산', '임신': '출산', '태어나': '출산', '신생아': '출산',
        '아기': '아기', '돌쟁이': '아기', '육아': '아기',
    }

    special_key = ''
    for kw, key in SPECIAL_KEYWORD_MAP.items():
        if kw in original_text:  # 원문으로 감지!
            special_key = key
            break

    if special_key and special_key in SPECIAL_TEMPLATES:
        empathy = random.choice(SPECIAL_TEMPLATES[special_key])
    else:
        empathy_prompt = f"""사용자가 "{original_text}" 라고 입력했어요.
Drive: N={drive.get('N')} W={drive.get('W')} Ψ={drive.get('Psi')}

딱 한 줄만 출력하세요:
- 사용자 원문의 핵심 단어(장소/용도/제품) 자연스럽게 포함
- 따뜻하고 감각적인 표현 + 이모지
- "찾아드리다", "도와드리다" 쇼핑 문맥 표현
- 질문 금지

예시:
베란다 의자 → "베란다를 더 편안하게 만들어줄 딱 맞는 의자 찾아드릴게요! 🌿🪑"
서재용 의자 → "서재를 완성할 편안하고 멋진 의자 찾아드릴게요! 📚🪑"
거실 러그 → "거실을 더 포근하게 만들어줄 러그 찾아드릴게요! 🏠✨"
재택근무 책상 → "집에서도 집중되는 나만의 책상 공간, 함께 찾아드릴게요! 💻✨"
"""
        empathy = call_llm(empathy_prompt, max_tokens=100).strip()

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

    # Context 선택 필요: 버튼형 선택 대기
    if board_result['type'] == 'context_select':
        # 이미 인원수 선택됐으면 2구역 스킵 → 바로 3구역
        selected_now = getattr(normalize_query, '_selected', {})
        if '인원수' in selected_now:
            inowon = selected_now['인원수']
            print(f'[2구역스킵] 인원수={inowon} 이미 선택됨 → 3구역 직행')
            session['context'] = inowon
            session['auto_selected'] = selected_now
            try:
                r = _route(raw_text)
                clean_product = r.get('product', raw_text)
                board_text = _get_new_board(clean_product, context=inowon, choice=selected_now)
                if board_text and not board_text.startswith('CONTEXT_SELECT:'):
                    session['stage'] = 'board_shown'
                    session['product_name'] = clean_product
                    session['raw_product'] = raw_text
                    # 동적 옵션 추가
                    extra_conditions = []
                    for k, v in selected_now.items():
                        if k not in {'소재','인원수','사이즈','용도','형태','색상','가격'} and f'[{k}]' not in board_text:
                            if k == '프레임':
                                extra_conditions.append(f'다리소재={v}')
                            else:
                                extra_conditions.append(f'{k}={v}')
                    if extra_conditions:
                        board_text = add_dynamic_options(board_text, ' '.join(extra_conditions), clean_product)
                    return empathy + "\n\n" + board_text
            except Exception as e:
                print(f'[2구역스킵 오류] {e}')
        session['stage'] = 'context_wait'
        session['auto_selected'] = getattr(normalize_query, '_selected', {})
        return empathy + "\n\n" + board_result['text']

    # 상황판 출력 + 동적 옵션 추가
    session['stage'] = 'board_shown'
    board_text = board_result['text']

    # dynamic_extra (보드에 없는 새 옵션) 처리
    _sel = getattr(normalize_query, '_selected', {})
    _d_extra = _dynamic_extra

    # OPTION_ALIAS pre-check는 selected 루프에서 처리
    # original_text 통째로 보내지 않음 (LLM이 여러줄 출력해서 첫줄만 처리되는 문제)

    # 1. dynamic_extra로 새 항목 추가 (매트리스강도/종류 등)
    if _d_extra:
        print(f'[dynamic_extra 처리] {_d_extra}')
        board_text = add_dynamic_options(board_text, _d_extra, session.get('product_name', ''))

    # 2. selected 조건들 → 하나씩 끊어서 처리 (인간 독해 방식)
    selected = getattr(normalize_query, '_selected', {})

    BOARD_STANDARD_KEYS = {'소재', '인원수', '사이즈', '용도', '형태', '색상',
                           '가격', '종류', '패브릭기능', '커버세탁', '헤드유무',
                           '좌방석쿠션', '수납형태', '프레임높이', '마감',
                           '매트리스종류', '프레임색상', '사이즈규격', 'dynamic_extra',
                           '매트리스'}

    SKIP_CATEGORIES = {'사이즈', '크기', '인원수', '침대크기', '침대사이즈',
                       '소파크기', '책상크기', '제품크기', '규격'}

    _product_name = session.get('product_name', '') or raw_text.split()[0]

    for k, v in selected.items():
        if not k or not v:
            continue
        if k in BOARD_STANDARD_KEYS:
            continue
        # 조건 하나씩 → add_dynamic_options
        if k == '프레임':
            condition = f'다리소재={v}'
        else:
            condition = f'{k}={v}'
        print(f'[selected루프] {condition}')
        board_text = add_dynamic_options(
            board_text, condition, _product_name,
            skip_categories=SKIP_CATEGORIES
        )

    return empathy + "\n\n" + board_text


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
