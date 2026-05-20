# ===============================
# recommendation.py
# 픽코 PICK 추천 엔진
# ===============================
#
# 포함 함수:
#   make_recommendation()       - 픽코 PICK Top3 생성
#   get_more_recommendations()  - 더보기
#
# 리뷰 분석/생성 → review_builder.py
# 블로그 검색    → naver_api.py
# ===============================
#
# ⚠️ ⚠️ ⚠️ 코드 작성 전 반드시 확인! ⚠️ ⚠️ ⚠️
#
# 여기에 코딩하는게 맞나요? 규칙을 지키세요!
#
# ✅ 여기에 올 수 있는 것:
#    - 추천 로직 (make_recommendation, get_more_recommendations)
#    - 다른 파일 함수 import
#
# ❌ 여기에 오면 안 되는 것:
#    - 네이버 API 호출 → naver_api.py
#    - 리뷰 분석/생성 함수 → review_builder.py
#    - 제품 필터링 함수 → naver_api.py
#    - def 로 시작하는 새 함수 정의 (추천로직 제외)
#
# ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️
# ===============================

import os
import re
import json
import time
import urllib.request

from sensor_layer  import sensor_layer
from policy_layer  import SYSTEM_RULES

# ── 리뷰 분석/생성 (review_builder.py) ──
from review_builder import (
    EXCLUDE_PATTERNS,
    GENUINE_REVIEW_KEYWORDS,
    _detect_axis,
    _build_picko_ratings,
    _build_user_voices,
    _build_picko_summary,
    _build_emotional_reason,
    _build_pros_cons_oneline,
)

# ── 블로그/카페 후기 수집 (naver_api.py) ──
from naver_api import (
    _search_naver_content,
    _build_review_queries,
    _collect_blog_reviews,
)

# ── 더보기 캐시 (세션별 grade_pools 저장) ──
_MORE_CACHE = {}  # key → {'pools': {grade: [products]}, 'shown': {grade: int}, 'expires': float}
_MORE_CACHE_TTL = 1800  # 30분
_CONTEXT_CACHE = {}  # 마지막 추천 리뷰 캐시 (맥락 대화용)

# ★ user_profile 캐시
# 지금은 세션 기반 (새로고침 시 초기화) - 테스트용
# ⚠️ 서비스 시 로컬스토리지 or TTL 캐시로 확장 필요
_USER_PROFILE_CACHE = {}  # sid → user_profile

def get_user_profile(session):
    """user_profile 가져오기"""
    sid = (session or {}).get('_sid', '')
    if sid and sid in _USER_PROFILE_CACHE:
        return _USER_PROFILE_CACHE[sid]
    return session.get('user_profile', {})

def save_user_profile(session, profile):
    """user_profile 저장"""
    sid = (session or {}).get('_sid', '')
    if sid:
        _USER_PROFILE_CACHE[sid] = profile
    session['user_profile'] = profile

# 환경변수는 naver_api.py에서 관리
# recommendation.py는 import만 사용


def make_recommendation(product_name, selections, extra='', session=None, card_queue=None):
    """제약 감지 + 리뷰 역추적 + Top 3"""
    from main import call_llm, get_constraint_hint, _search_worry_info
    from naver_api import search_naver_shopping_images
    from context_manager import build_user_context, make_context_llm

    # raw_product에 선택 조건 합치기 (케이스2,3 해결!)
    # "소파" → "4인용 패브릭 소파"
    raw_product = (session or {}).get('raw_product', product_name)
    _original_product = raw_product  # ★ 보강 전 원래 제품명 저장! (넓게 검색용)

    # ★ 직접입력 추출 (맥락 생성에 필요!)
    import re as _re_ctx
    _direct_input_ctx = ''
    _ctx_match = _re_ctx.search(r'직접입력:(.+?)(?=\s+\w+:|$)', selections)
    if _ctx_match:
        _direct_input_ctx = _ctx_match.group(1).strip()
    else:
        _di_idx = selections.find('직접입력:')
        if _di_idx >= 0:
            _direct_input_ctx = selections[_di_idx + len('직접입력:'):].strip()

    # ★ 맥락 생성 + call_llm 래핑 (최대한 앞에서!)
    # → 이후 모든 LLM 호출에 자동으로 맥락 흐름!
    _session_id = (session or {}).get('_sid', '')
    _user_context = build_user_context(raw_product, selections, _direct_input_ctx, _session_id)

    # ★ 마음 상황판 정보 합치기 (LLM이 사용자 상황을 항상 볼 수 있도록)
    # ★ 픽코 헌법 포함
    _PICKO_ID = "You are Picko. A shopping critic on the user's side. User is a first-time buyer solving a problem, not buying a product. Never: fake confidence, pushy recommendations, ad-style language."
    _user_context = _PICKO_ID + ' / ' + _user_context

    _profile = (session or {}).get('user_profile', {})
    if _profile:
        _pp = []
        for _pk, _pv in _profile.items():
            if str(_pk).startswith('_'): continue
            if isinstance(_pv, list) and _pv:
                _pp.append(', '.join([str(x) for x in _pv]))
            elif _pv:
                _pp.append(str(_pv))
        if _pp:
            _user_context += ' / 마음상황판: ' + ' / '.join(_pp)

    print(f'[사용자맥락] {_user_context}')
    call_llm = make_context_llm(call_llm, _user_context)
    
    # selections에서 인원수/소재 등 핵심 조건 추출
    PRIORITY_KEYS = ['인원수', '소재', '사이즈']  # 형태/용도 제외! 3인용 패브릭이 핵심
    sel_prefix = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k in PRIORITY_KEYS and v and v not in raw_product:
                sel_prefix.append(v)
    # raw_product 앞에 핵심 조건 붙이기
    if sel_prefix:
        raw_product = ' '.join(sel_prefix) + ' ' + raw_product
        print(f'[쿼리보강] {raw_product}')

    keyword = raw_product + ' ' + selections
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

    print(f'[추천시작] 제품={raw_product} / 조건={selections}')
    naver_products = []
    citation_sources = []
    review_warnings = {}
    review_tags = {}
    sensor_score = 0

    # ── single_product 모드 먼저 확인 ──
    _single_mode = (session or {}).get('single_product', False)

    # 직접입력 먼저 추출 (후기 수집에 필요! 공백 포함이라 별도 파싱)
    _direct_input = ''
    import re as _re_direct
    _direct_match = _re_direct.search(r'직접입력:(.+?)(?=\s+\w+:|$)', selections)
    if _direct_match:
        _direct_input = _direct_match.group(1).strip()
    if not _direct_input:
        # 폴백: "직접입력:" 이후 전체
        _di_idx = selections.find('직접입력:')
        if _di_idx >= 0:
            _direct_input = selections[_di_idx + len('직접입력:'):].strip()

    # ── 블로그 후기 수집 준비 ──
    if _single_mode:
        blog_product = raw_product
        print(f'[후기수집] 단일제품 모드: {blog_product}')
    else:
        blog_product = raw_product
        print(f'[후기쿼리] {blog_product}')

    _session_brand = (session or {}).get('single_brand', '')
    if _single_mode and not _session_brand:
        _session_brand = raw_product.split()[0] if raw_product else ''
    _brand_filter = _session_brand if _single_mode else ''
    print(f'[브랜드필터확인] brand_filter={_brand_filter}')

    # ── 자연어 쿼리 생성 (review_builder.py 담당!) ──
    from review_builder import build_natural_query
    _board_query, _direct_query = build_natural_query(
        raw_product=raw_product,
        selections=selections,
        direct_input=_direct_input,
        call_llm_fn=call_llm,
    )

    # ★ 브랜드 단일 모드: board_query 없으면 제품명으로 사람언어 생성
    if _single_mode and not _board_query:
        try:
            _product_kw = raw_product.split()[-1] if raw_product else ''
            _brand_kw = raw_product.split()[0] if raw_product else ''
            _single_prompt = (
                f'제품: {raw_product}\n\n'
                f'이 제품을 구매한 실제 사람이 블로그에 검색할 법한 검색어를 만들어줘.\n'
                f'규칙:\n'
                f'- 브랜드명 "{_brand_kw}" 또는 제품 핵심어 "{_product_kw}" 포함\n'
                f'- "내돈내산" "솔직후기" "실사용후기" 중 하나 포함\n'
                f'- 상품 카탈로그 언어 금지\n'
                f'- 5단어 이내, 1줄만 출력'
            )
            _board_query = call_llm(_single_prompt, max_tokens=30).strip().split('\n')[0]
            print(f'[자연어쿼리-단일모드] "{_board_query}"')
        except Exception:
            _board_query = f'{raw_product} 내돈내산'
            print(f'[자연어쿼리-단일폴백] "{_board_query}"')

    # ★★ 병렬 블로그 수집 (naver_api.py 담당!)
    from naver_api import collect_blog_parallel
    blog_reviews, _board_reviews, _direct_reviews = collect_blog_parallel(
        blog_product=blog_product,
        raw_product=raw_product,
        selections=selections,
        extra=extra,
        brand_filter=_brand_filter,
        board_query=_board_query,
        direct_query=_direct_query,
    )
    _blog_reviews_cache = blog_reviews
    print(f'[병렬수집완료] 기본={len(blog_reviews)} 상황판={len(_board_reviews)} 직접={len(_direct_reviews)}개')

    # ★ STEP2: 광고 제거 + 진짜 후기 판별 (review_builder.py 담당!)
    from review_builder import filter_genuine_reviews
    _all_reviews = _board_reviews + _direct_reviews + blog_reviews
    _genuine_reviews, _ad_count, _suspect_count = filter_genuine_reviews(_all_reviews)

    # ★ 뉴스 검색 트리거 감지 (TV광고/리콜/논란만!)
    NEWS_TRIGGERS = {
        'tv광고', '티비광고', '광고나오는', '광고 나오는',
        'tv에나오는', '티비에나오는', '광고제품',
        '리콜', '결함', '화재', '위험제품',
        '문제있는', '이슈', '논란', '가격담합',
    }
    _news_brands = []
    _direct_lower = _direct_input.lower().replace(' ', '') if _direct_input else ''
    _news_trigger = any(t in _direct_lower or t in _direct_input for t in NEWS_TRIGGERS)

    if _news_trigger and _direct_input:
        try:
            from naver_api import search_naver_news
            # ★ 뉴스 쿼리는 짧게! 제품명 + 핵심 키워드만!
            # TV광고 → "침대 광고 브랜드"
            # 리콜   → "침대 리콜"
            _news_core = ''
            if any(t in _direct_lower for t in ['tv광고', '티비광고', '광고나오는', '광고 나오는', '티비에나오는', '광고제품']):
                _news_core = '광고 브랜드'
            elif any(t in _direct_input for t in ['리콜', '결함', '화재']):
                _news_core = '리콜 결함'
            elif any(t in _direct_input for t in ['논란', '이슈', '담합']):
                _news_core = '논란 이슈'
            else:
                _news_core = _direct_input[:5]

            _news_query = f'{raw_product} {_news_core}'
            print(f'[뉴스트리거] "{_news_query}" 뉴스 검색 시작!')
            _news_items = search_naver_news(_news_query, limit=10)
            if _news_items:
                # ★ 광고/리콜 관련 기사만 필터링!
                # 엉뚱한 기사(춘천옥/흙마루 같은) 제거!
                _AD_NEWS_KEYWORDS = ['광고', '모델', 'TV', '티비', '브랜드', '리콜', '결함', '논란']
                _filtered_news = [
                    n for n in _news_items
                    if any(kw in n['text'] for kw in _AD_NEWS_KEYWORDS)
                ]
                if not _filtered_news:
                    _filtered_news = _news_items  # 필터 결과 없으면 전체 사용
                print(f'[뉴스필터] {len(_news_items)}개 → {len(_filtered_news)}개 (관련 기사만)')

                _news_text = '\n'.join([n['text'][:100] for n in _filtered_news[:8]])
                _news_brand_prompt = (
                    f'다음 뉴스에서 {raw_product} 제조/판매 브랜드명만 추출하세요.\n'
                    f'★ 실제 {raw_product} 브랜드만! 지역명/서비스명 제외!\n'
                    f'★ 브랜드명만 콤마로! 설명/문장 절대 금지!\n'
                    f'예: 삼성,LG,시몬스,에이스\n\n'
                    f'{_news_text}'
                )
                _news_brand_result = call_llm(_news_brand_prompt, max_tokens=50).strip()
                _news_brand_result = _news_brand_result.split('\n')[0].strip()
                if _news_brand_result and _news_brand_result != '없음' and len(_news_brand_result) < 50:
                    for _nb in _news_brand_result.split(','):
                        _nb = _nb.strip()
                        if _nb and 2 <= len(_nb) <= 15:
                            if not any(c in _nb for c in ['(', ')', '.', '없음']):
                                _news_brands.append(_nb)
                                print(f'[뉴스브랜드] {_nb}')
        except Exception as _ne:
            print(f'[뉴스검색오류] {_ne}')

    # ★ STEP3: 진짜 후기에서 LLM으로 브랜드 자동 추출
    _review_matched_brands = _news_brands  # 뉴스 브랜드 우선 포함!

    # 조건 키워드 추출 (직접입력 + 상황판)
    _check_keywords = []
    if _direct_input:
        _check_keywords.extend([w for w in _direct_input.split()
                                if len(w) >= 2 and w not in {'유아', '제품', '것이', '있는', '없는', '않는', '찾아요'}])
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', '색상', 'E', '직접입력'] and v and len(v) >= 2:
                _check_keywords.append(v)
    if _check_keywords:
        print(f'[리뷰매칭키워드] {_check_keywords[:5]}')

    if _check_keywords and _direct_reviews:
        # 직접입력 후기에서만 매칭! (blog_reviews 혼합 금지)
        _matched_reviews = []
        for review in _direct_reviews:
            review_text = review if isinstance(review, str) else review.get('text', '')
            matched_kw = [kw for kw in _check_keywords if kw in review_text]
            if matched_kw:
                _matched_reviews.append((review_text, matched_kw))

        if _matched_reviews:
            # LLM으로 브랜드 추출
            _brand_extract_prompt = (
                '다음 후기들에서 제품 브랜드명만 추출하세요.\n'
                '브랜드명만 콤마로 구분해서 출력. 없으면 "없음".\n'
                '★ 설명/이유/문장 절대 금지! 브랜드명만!\n'
                '예: 튜즐,노르잇,버드베베\n\n'
            )
            for _rt, _mk in _matched_reviews[:5]:
                _brand_extract_prompt += f'후기: {_rt[:100]}\n'

            try:
                _brand_result = call_llm(_brand_extract_prompt, max_tokens=50).strip()
                # ★ 설명이 들어온 경우 첫 줄만 사용!
                _brand_result = _brand_result.split('\n')[0].strip()
                # ★ 너무 길면 브랜드 아님 (설명 포함)
                if _brand_result and _brand_result != '없음' and len(_brand_result) < 50:
                    for _b in _brand_result.split(','):
                        _b = _b.strip()
                        # ★ 괄호/특수문자 포함 시 브랜드 아님!
                        if _b and len(_b) >= 2 and len(_b) <= 15 and _b not in _review_matched_brands:
                            if not any(c in _b for c in ['(', ')', '.', '없음', '없']):
                                _review_matched_brands.append(_b)
                                print(f'[후기브랜드LLM] {_b}')
            except Exception as _be:
                print(f'[브랜드추출오류] {_be}')

    if _review_matched_brands:
        print(f'[후기역추적] 브랜드: {_review_matched_brands[:3]}')

    # ★ STEP4: 브랜드 1:1 슬롯 수집 (naver_api.py 담당!)
    from naver_api import search_brand_slots
    _product_kw = raw_product.split()[-1]
    _must_cond = {}
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '인원수' and v:
                _must_cond['인원수'] = v
            elif k == '소재' and v:
                _must_cond['소재'] = v
    _brand_slots, _seen_products = search_brand_slots(
        brands=_review_matched_brands,
        product_kw=_product_kw,
        must_conditions=_must_cond,
        call_llm_fn=call_llm,
    )
    if _review_matched_brands:
        print(f'[후기역추적] 브랜드: {_review_matched_brands[:3]}')

    # ★ 바람잡이: 상황판에 특정 조건 선택 시 해당 조건 브랜드 추가 확보!
    # 예: 스툴포함 선택 → 스툴포함 브랜드 별도 수집 → 메인 풀에 합치기
    _wind_conditions = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '스툴' and v == '스툴포함':
                _wind_conditions.append('스툴포함')

    if False and _wind_conditions:  # 바람잡이 잠시 중단! (코드 삭제 금지)
        from naver_api import search_wind_slots
        for _cond in _wind_conditions:
            _wind_slots = search_wind_slots(raw_product, _cond, call_llm_fn=call_llm)
            if _wind_slots:
                _brand_slots = _wind_slots + _brand_slots
                _seen_products.update(p['name'][:20] for p in _wind_slots)
                print(f'[바람잡이합산] {_cond} → {len(_wind_slots)}개 추가!')
    # 경고 → 알고 사세요 자동 생성
    auto_cautions = []
    if '색상경고' in review_warnings:
        auto_cautions.append('실제 색상이 상세페이지와 다를 수 있어요. 구매 전 색상 샘플 요청 추천!')
    if '배송경고' in review_warnings:
        auto_cautions.append('배송이 다소 오래 걸릴 수 있어요. 여유있게 주문하세요.')
    auto_cautions_str = '\n'.join(auto_cautions) if auto_cautions else ''

    # 태그 → 매칭 조건 자동 생성
    auto_tags_str = ', '.join(review_tags.keys()) if review_tags else ''
    print(f'[센서결과] 경고={list(review_warnings.keys())} 태그={auto_tags_str} 점수={sensor_score}')



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

    # ── 실제 네이버 쇼핑 제품 수집 (naver_api.py 담당!) ──
    from naver_api import search_naver_images, search_naver_shopping_full as _search_naver_shopping_full

    # 실제 제품 검색: 선택 조건 포함해서 검색 (4인용 패브릭 소파 등)
    # raw_product만 쓰면 "소파"만 검색 → 아무 소파나 나옴
    # 선택 조건에서 핵심 키워드 추출
    PRIORITY_KEYS = ['인원수', '소재', '사이즈', '수납형태']  # 수납형태 추가 (서랍형/리프트형)
    sel_priority = []
    sel_normal = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', '색상', 'E', '직접입력'] and v:
                if k in PRIORITY_KEYS:
                    sel_priority.append(v)
                else:
                    sel_normal.append(v)
    # 우선순위 조건 앞에, 나머지 뒤에
    sel_for_search = sel_priority + sel_normal
    # 색상 추출
    _color_val = ''
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '색상' and v:
                _color_val = v
                break

    # ★★★ 새 방식: 넓게 검색 → LLM이 골라내기!
    # (기존 잠금) search_with_sel = build_search_query(...)
    search_with_sel = _original_product  # 보강 전 제품명! 넓게!
    print(f'[검색쿼리-넓게] {search_with_sel}')
    # 가격 등급 파싱 (저가/중가/고가/최고가) - 필터링은 4분위로
    _grade = ''
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '가격' and v:
                _grade = v.strip()
                break
    if _grade:
        print(f'[가격등급선택] {_grade}')

    # 슬롯 남은 제품 먼저 → 부족하면 200개 보충 (naver_api.py 담당!)
    from naver_api import search_pool_filtered
    _POOL_MIN = 9  # 더보기 최소 (저/중/고/최고가 각 3개 * 3)
    _pool_products = []

    # ★ 브랜드 슬롯 태깅은 naver_api.py에서 처리!
    # search_brand_slots → from_review=True
    # search_pool_filtered → from_review=False

    # 슬롯 제품이 부족할 때만 200개 수집
    if len(_brand_slots) < _POOL_MIN:
        _pool_products = search_pool_filtered(
            query=search_with_sel,
            seen_products=_seen_products,
        )
        # ★ 0개면 제품명만으로 재시도! (쿼리 넓히기)
        if not _pool_products and search_with_sel != raw_product:
            print(f'[풀재시도] "{search_with_sel}" → 0개! "{raw_product}"로 재시도')
            _pool_products = search_pool_filtered(
                query=raw_product,
                seen_products=_seen_products,
            )
        
        # ★ 바람잡이 다양성! 편중 방지!
        if _pool_products and len(_pool_products) > 20:
            try:
                _div_prompt = (
                    f"'{_original_product}'을 네이버에서 다양하게 찾기 위한 검색어 2개만.\n"
                    f"기본 검색으로 이미 많이 나온 종류 말고, 다른 종류로!\n"
                    f"한 줄에 하나. 다른 말 금지."
                )
                _div_result = call_llm(_div_prompt, max_tokens=30).strip()
                for _dline in _div_result.split('\n'):
                    _dq = _dline.strip()
                    if _dq and len(_dq) > 2:
                        _extra = search_pool_filtered(query=_dq, seen_products=_seen_products)
                        if _extra:
                            _pool_products.extend(_extra)
                            _seen_products.update(p['name'][:20] for p in _extra)
                            print(f'[바람잡이다양성] "{_dq}" → +{len(_extra)}개')
            except Exception as e:
                print(f'[바람잡이오류] {e}')
        
        print(f'[풀보충] 슬롯{len(_brand_slots)}개 부족 → {len(_pool_products)}개 보충')
    else:
        print(f'[풀스킵] 슬롯{len(_brand_slots)}개 충분 → 200개 수집 생략!')

    # 브랜드 슬롯 1순위 + 풀 보충 합산
    real_products = _brand_slots + _pool_products
    print(f'[최종제품풀] 슬롯{len(_brand_slots)}+풀{len(_pool_products)} = {len(real_products)}개')

    # ★ 바람잡이 2.0: 풀 수집 후 동적 브랜드 추출 + 추가조건 재요청!
    # 범용! 어떤 카테고리든 작동!
    from naver_api import WIND_CONDITIONS, search_wind_slots
    _wind_extra = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if v in WIND_CONDITIONS:
                _wind_extra.append(WIND_CONDITIONS[v])

    if _wind_extra and _pool_products:
        _wind_slots2 = search_wind_slots(raw_product, _pool_products, _wind_extra)
        if _wind_slots2:
            # URL로 중복체크 (이름 앞20자는 스툴포함/미포함 구분 못함!)
            _existing_urls = {p.get('product_url', p['name'][:30]) for p in real_products}
            _unique = [p for p in _wind_slots2
                      if p.get('product_url', p['name'][:30]) not in _existing_urls]
            real_products = _unique + real_products
            print(f'[바람잡이2.0합산] {" ".join(_wind_extra)} → {len(_unique)}개 추가!')

    # 가격 범위는 위에서 이미 파싱됨

    # 수집된 제품 필터링
    import re as _re2
    RENTAL_KEYWORDS = ['렌탈', '구독', '약정', '월납', '리스']
    brand_kw = raw_product.split()[0]
    category_kw = raw_product.split()[-1]

    # 0. LLM 필터 임시 비활성화 (가격 필터 안정화 후 재활성화)
    if False and len(real_products) > 3 and not _single_mode:
        try:
            product_list = '\n'.join([f'{i+1}. {p["name"]}' for i, p in enumerate(real_products[:30])])
            # 사용자 맥락 생성 (1단계: 자동 생성!)
            sel_context = []
            for part in selections.split():
                if ':' in part:
                    k, v = part.split(':', 1)
                    if k not in ['가격', 'E'] and v:
                        sel_context.append(f'{k}:{v}')
            price_context = ''
            _pm = _re_p2.search(r'(\d+)만원\s*~\s*(\d+)만원', selections)
            if _pm:
                price_context = f'가격대: {_pm.group(1)}~{_pm.group(2)}만원'

            filter_prompt = (
                f"[사용자 구매 여정]\n"
                f"찾는 제품: {raw_product}\n"
                f"선택 조건: {', '.join(sel_context)}\n"
                f"{price_context}\n\n"
                f"위 사용자가 구매하려는 제품과 동일한 완성형 제품만 골라줘.\n\n"
                f"선택 기준:\n"
                f"- 거실에 즉시 놓고 앉을 수 있는 완성형 소파 본체\n\n"
                f"절대 제외:\n"
                f"- 커버, 덮개, 천갈이, 리폼, 패드, 매트, 방석, 블랭킷\n"
                f"- P숫자로 시작하는 제품\n"
                f"- 카페/병원/사무실 상업용\n\n"
                f"번호만 콤마로 답해줘. 없으면 '없음'\n\n{product_list}"
            )
            llm_result = call_llm(filter_prompt, max_tokens=100).strip()
            # 번호 추출
            import re as _re_llm
            nums = [int(n)-1 for n in _re_llm.findall(r'\d+', llm_result) if 0 < int(n) <= len(real_products)]
            if nums:
                llm_filtered = [real_products[i] for i in nums if i < len(real_products)]
                print(f'[LLM필터] {len(real_products)}개 → {len(llm_filtered)}개')
                real_products = llm_filtered
        except Exception as e:
            print(f'[LLM필터오류] {e}')

    # P숫자 + 상업용 + 악세서리 + 배송안내 즉시 제거!
    import re as _re_p
    ACCESSORY_KW = ['커버', '패드', '천갈이', '덮개', '방석', '블랭킷', '보호대',
                    '다리커버', '고정봉', '고정핀', '마루보호', '소음방지', '리폼',
                    '스킨', '갈이', '시트', '베개커버']
    real_products = [p for p in real_products
        if not _re_p.match(r'^P[0-9]+', p['name'])
        and not p['name'].startswith('[')   # [ 예약배송 ] 등 배송안내 제거!
        and not any(kw in p['name'] for kw in ['학교', '병원', '카페', '사무실', '센터', '요양원', '교회'])
        and not any(kw in p['name'] for kw in ACCESSORY_KW)]
    print(f'[악세서리제외] → {len(real_products)}개')

    # ★ 카테고리 불일치 제거 (유모차 → 강아지 제외)
    PET_KEYWORDS = ['강아지', '애견', '반려동물', '펫', '개모차', '고양이', '반려견']
    if '유모차' in raw_product:
        before = len(real_products)
        real_products = [p for p in real_products if not any(kw in p['name'] for kw in PET_KEYWORDS)]
        removed = before - len(real_products)
        if removed:
            print(f'[개모차제거] {removed}개 제거 → {len(real_products)}개')
    
    # 1. 렌탈/구독 제품 제외
    filtered_products = [
        p for p in real_products
        if not any(kw in p['name'] for kw in RENTAL_KEYWORDS)
    ]

    # 2. 인원수 필터 (4인용 선택 시 1인/2인 제외)
    _person_val = ''
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '인원수': _person_val = v
    if _person_val:
        WRONG_PERSONS = {'1인용':['1인','1인용'],'2인용':['1인','1인용','2인','2인용'],'3인용':['1인','2인'],'4인용':['1인','2인']}.get(_person_val, [])
        person_filtered = [p for p in filtered_products if not any(w in p['name'] for w in WRONG_PERSONS)]
        if person_filtered:
            filtered_products = person_filtered
            print(f'[인원필터] {_person_val} → {len(filtered_products)}개')

    # 3. 중복 제품 제거 (브랜드+모델 유사한 것)
    seen_brands = []
    seen_model_keys = []  # ★ OEM 중복제거 (비비소파 티스 = 케어퍼니처 티스)
    unique_products = []
    for p in filtered_products:
        # 브랜드(첫 단어)만 기준으로 중복 제거 (모델은 달라도 됨)
        brand_key = p['name'].split()[0] if p['name'] else ''
        # ★ OEM 중복제거: 첫 단어 제외 나머지로 비교
        name_parts = p['name'].split()
        model_key = ' '.join(name_parts[1:4]) if len(name_parts) > 1 else ''
        if brand_key not in seen_brands and model_key not in seen_model_keys:
            seen_brands.append(brand_key)
            if model_key:
                seen_model_keys.append(model_key)
            unique_products.append(p)
        elif model_key and model_key in seen_model_keys:
            print(f'[OEM중복제거] {p["name"][:30]}')
    filtered_products = unique_products
    print(f'[중복제거] → {len(filtered_products)}개')

    # 4. 4분위 가격 필터
    _actual_price_range = ''
    if filtered_products:
        priced = []
        for p in filtered_products:
            try:
                price_str = p.get('price', '0').replace(',', '').replace('원', '')
                price = int(price_str) if price_str else 0
                if price > 0:
                    priced.append((price, p))
            except:
                pass
        priced.sort(key=lambda x: x[0])
        n = len(priced)
        if n >= 4:
            q = n // 4
            # ★ 교차 가격 구간! 구간이 겹쳐서 제품이 못 빠져나감!
            # 저가~최고가 어느 구간이든 진입 가능!
            half = max(q // 2, 1)
            GRADE_RANGE = {
                '저가':   (0,          min(q + half, n)),
                '중가':   (max(q - half, 0),  min(q*2 + half, n)),
                '고가':   (max(q*2 - half, 0), min(q*3 + half, n)),
                '최고가': (max(q*3 - half, 0), n),
            }
            # ★ 더보기 캐시는 항상 저장! (가격 선택 여부 무관)
            _pending_cache_key = str(session.get('product_name','')) + str(session.get('selections',''))
            _pending_priced = priced
            _pending_grade_range = GRADE_RANGE

            if _grade:
                lo, hi = GRADE_RANGE.get(_grade, (0, n))
                selected_priced = priced[lo:hi]
                filtered_products = [p for _, p in selected_priced]
                p_lo = priced[lo][0] // 10000 if lo < n else 0
                p_hi = priced[min(hi, n)-1][0] // 10000 if hi > 0 else 0
                _actual_price_range = f'{p_lo}만~{p_hi}만원'
                print(f'[4분위필터] {_grade} → {len(filtered_products)}개 ({_actual_price_range})')
            else:
                # 가격 미선택 → 전체 사용, 더보기는 4분위로 제공
                filtered_products = [p for _, p in priced]
                print(f'[가격미선택] 전체 {len(filtered_products)}개 → 더보기 4분위 저장')
        elif n > 0:
            # ★ 4개 미만이어도 더보기 캐시 저장! (슬롯 제품 보관)
            from naver_api import make_small_grade_range
            _SMALL_GRADE_RANGE = make_small_grade_range(priced)
            _pending_cache_key = str(session.get('product_name','')) + str(session.get('selections',''))
            _pending_priced = priced
            _pending_grade_range = _SMALL_GRADE_RANGE
            filtered_products = [p for _, p in priced]
            print(f'[소수제품] {n}개 → 전체 구간 더보기 저장!')

    if filtered_products:
        real_products = filtered_products

    print(f'[실제제품] 관련 제품 필터 후 {len(real_products)}개')

    # ★ 브랜드 슬롯 생존/탈락 확인 로그 (1차 테스트!)
    _review_names = {s['name'][:20] for s in _brand_slots}
    _survived_review = [p for p in real_products if p.get('from_review')]
    _lost_review = [s for s in _brand_slots
                    if s['name'][:20] not in {p['name'][:20] for p in real_products}]
    print(f'[리뷰출신] 생존={len(_survived_review)}개 / 탈락={len(_lost_review)}개')
    for s in _lost_review:
        price = s.get('price', '?')
        print(f'[리뷰탈락] {s["name"][:30]} ({price}원) ← 4분위 {_grade} 구간 밖!')
    _price_not_found = len(real_products) < 2

    # ★ 조건 매칭 점수 정렬 (제거 아님! 순서만 조정)
    # ★ LLM 기반 범용 조건 매칭 (naver_api.py 담당!)
    from naver_api import score_products_by_conditions
    _check_vals = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', '색상', 'E', '직접입력', '사이즈'] and v:
                _check_vals.append(v)

    # ★ 직접입력 핵심 키워드도 조건매칭에 추가!
    if _direct_input:
        import re as _re_di
        _di_words = _re_di.findall(r'[가-힣a-zA-Z]{2,}', _direct_input)
        _DI_STOPWORDS = {'있는', '없는', '찾아', '골라', '주세요', '싶어요', '원단으로', '제품으로'}
        _di_keywords = [w for w in _di_words if w not in _DI_STOPWORDS][:3]
        _check_vals.extend(_di_keywords)
        if _di_keywords:
            print(f'[직접입력조건] {_di_keywords} → 조건매칭 추가!')

    if _check_vals:
        _scored = score_products_by_conditions(real_products, _check_vals, call_llm)
        real_products = [p for p, _ in _scored]
        _score_map = {p['name']: s for p, s in _scored}
        _match_count = sum(1 for _, s in _scored if s > 0)
        _max_score = max(s for _, s in _scored) if _scored else 0
        _no_match_hint = '' if _match_count > 0 else \
            f'\n참고: 제품명에서 {_check_vals} 조건을 확인하기 어려워요. 유사 제품으로 안내해주세요.'
    else:
        _score_map = {}
        _no_match_hint = ''

    _match_score = lambda p: _score_map.get(p.get('name', ''), 0)

    # ★★★ 새 방식: LLM이 마음+3구역 맥락 보고 6개 선택!
    _candidates = [p for p in real_products if p.get('image_url')][:30]
    _pick_count = min(6, len(_candidates))  # 후보 부족하면 있는 만큼만!

    if len(_candidates) >= 3:
        _candidate_list = []
        for i, p in enumerate(_candidates):
            _candidate_list.append(f'{i+1}. {p["name"][:40]} | {p.get("price","?")}원')

        _rank_prompt = (
            f'[출력형식] 서로 다른 제품 숫자 {_pick_count}개만 콤마로. 예시: 2,5,8\n'
            '[절대금지] 같은 번호 중복 선택 금지! 모두 다른 번호!\n'
            '[절대금지] 설명/이유/마크다운 금지\n'
            '[절대금지] 찾는 제품(' + product_name + ')과 다른 카테고리 제품 선택 금지\n'
            '[절대금지] 악세서리/부속품/시트/커버 선택 금지! 본체만!\n\n'
            '찾는 제품: ' + product_name + '\n'
            '사용자 선택 조건: ' + selections + '\n'
            '직접입력: ' + (_direct_input or '없음') + '\n\n'
            '아래 후보에서 사용자 조건에 가장 맞는 6개를 골라주세요.\n'
            '조건에 맞는 것 우선, 같은 카테고리만!\n\n'
            '후보:\n' + '\n'.join(_candidate_list) + '\n\n'
            '6개 번호만:'
        )
        try:
            _rank_result = call_llm(_rank_prompt, max_tokens=30).strip()
            print(f'[LLM선택원문] {_rank_result}')
            import re as _re_rank
            _found_nums = _re_rank.findall(r'\d+', _rank_result)
            # ★ 중복 제거!
            _seen_nums = set()
            _rank_nums = []
            for n in _found_nums:
                idx = int(n) - 1
                if 0 <= idx < len(_candidates) and idx not in _seen_nums:
                    _seen_nums.add(idx)
                    _rank_nums.append(idx)
            _rank_nums = _rank_nums[:6]
            print(f'[LLM선택파싱] 숫자={_found_nums} → 인덱스={_rank_nums}')
            if len(_rank_nums) >= 2:
                _ranked = [_candidates[i] for i in _rank_nums if i < len(_candidates)]
                _selected_idx = set(_rank_nums)
                for i, p in enumerate(_candidates):
                    if i not in _selected_idx:
                        _ranked.append(p)
                real_products = _ranked + [p for p in real_products if p not in _candidates]
                _names = [_candidates[i]["name"][:15] for i in _rank_nums if i < len(_candidates)]
                print(f'[LLM선택] {_rank_result} → {_names}')
        except Exception as e:
            print(f'[LLM선택오류] {e}')

    print(f'[픽코추천순서] 맥락 기반 6개 선택 완료')

    # ★ 10개 후보 블로그 검증! (naver_api.py 담당)
    # 제품명 + 직접입력으로 마음씨 확인!
    if _direct_input:
        from naver_api import verify_candidates_by_blog
        _verify_candidates = [p for p in real_products if p.get('image_url')][:10]
        _passed, _failed = verify_candidates_by_blog(
            _verify_candidates,
            direct_input=_direct_input,
            call_llm_fn=call_llm,
        )
        # 합격 → 픽코3 우선 / 탈락 → 뒤로
        real_products = _passed + _failed + [p for p in real_products if p not in _verify_candidates]
        print(f'[마음씨검증] 합격={len(_passed)}개 → 픽코3 / 탈락={len(_failed)}개 → 더보기')

    # ★ 리뷰 출신 1순위 보장 (naver_api.py 담당!)
    from naver_api import sort_review_first
    real_products = sort_review_first(real_products, direct_keywords=_di_keywords if '_di_keywords' in locals() else [])

    # ★ 픽코3 카드1 리뷰 출신 확인 로그
    _review_in_picko3 = sum(1 for p in real_products[:3] if p.get('from_review'))
    _pool_in_picko3 = 3 - _review_in_picko3
    print(f'[픽코3출신] 리뷰출신={_review_in_picko3}개 / 풀출신={_pool_in_picko3}개')

    # ★ vreview/크리마 자동 감지 + 공식몰 URL 전환
    from naver_api import auto_detect_and_fetch_reviews, find_official_url
    _vreview_added = 0
    for _rp in real_products[:3]:
        _purl = _rp.get('product_url', '')
        if not _purl:
            continue

        # 네이버 카탈로그/검색 URL → 공식몰 아님 → 건너뜀
        if 'search.shopping.naver.com' in _purl or 'shopping.naver.com/catalog' in _purl:
            print(f'[vreview스킵] 네이버 카탈로그 → 건너뜀: {_purl[:50]}')
            continue

        # 스마트스토어 → 공식몰 전환 시도
        _is_naver_store = ('smartstore.naver.com' in _purl or 'brand.naver.com' in _purl)
        _brand_from_name = _rp.get('name', '').split()[0] if _rp.get('name') else ''

        _official_url = ''
        if _is_naver_store and _brand_from_name:
            for _key, _info in __import__('naver_api').BRAND_REVIEW_API.items():
                if _key in _brand_from_name or _brand_from_name in _key:
                    _official_url = _info.get('main', '')
                    if _official_url:
                        print(f'[공식몰전환] {_brand_from_name} → {_official_url}')
                        break

        _target_url = _official_url if _official_url else _purl

        if _is_naver_store and not _official_url:
            print(f'[vreview스킵] 스마트스토어 전용 → 블로그만: {_purl[:50]}')
            continue

        try:
            _auto_reviews = auto_detect_and_fetch_reviews(
                product_url=_target_url,
                product_name=_rp.get('name', raw_product),
                limit=15,
            )
            if _auto_reviews:
                blog_reviews = _auto_reviews + blog_reviews
                _rp['official_reviews'] = _auto_reviews
                _rp['official_url']     = _target_url
                _rp['review_source']    = _auto_reviews[0].get('source', 'R1_vreview')
                _vreview_added += len(_auto_reviews)
                _src = _auto_reviews[0].get('source', '')
                print(f'[vreview자동] {_rp["name"][:25]} → {len(_auto_reviews)}개 ({_src})')
            else:
                print(f'[vreview없음] {_target_url[:50]} → 블로그만')
        except Exception as _ve:
            print(f'[vreview오류] {_target_url[:50]}: {_ve}')

    if _vreview_added:
        print(f'[vreview합산] 총 {_vreview_added}개 공식몰 리뷰 → 블로그와 합산!')

    naver_slots = []
    for rp in real_products:
        if len(naver_slots) >= 3: break
        if rp.get('image_url'):
            purl = rp.get('product_url', '')
            # URL 타입 로그
            if 'smartstore.naver.com' in purl:
                url_type = '스마트스토어'
            elif 'brand.naver.com' in purl:
                url_type = '브랜드스토어'
            elif 'cafe24.com' in purl:
                url_type = '카페24'
            elif 'shopdetail.html' in purl:
                url_type = '메이크샵'
            elif 'goods_view.php' in purl:
                url_type = '고도몰'
            elif 'coupang.com' in purl:
                url_type = '쿠팡'
            else:
                url_type = '독립몰/기타'
            print(f'[URL타입] {url_type} → {purl[:60]}')
            naver_slots.append({
                'image_url': rp['image_url'],
                'product_url': rp['product_url'],
                'name': rp['name'],
                'price': rp['price'],
                'mall': rp['mall'],
                'from_review': rp.get('from_review', False),
                'original': rp.get('original', False),
                'direct_blog_verified': rp.get('direct_blog_verified', False),
            })

    # 개인몰 크롤링은 추후 안정화 후 재활성화
    # 현재는 브랜드 직접 추천 방식 우선

    # 부족하면 일반 이미지로 보충
    if len(naver_slots) < 1:
        img_results = search_naver_images(raw_product, limit=6)
        for r in img_results:
            if len(naver_slots) >= 3: break
            if r.get('url'):
                naver_slots.append({'image_url': r['url'], 'product_url': '', 'name': '', 'price': '', 'mall': ''})

    while len(naver_slots) < 3:
        naver_slots.append({'image_url': '', 'product_url': '', 'name': '', 'price': '', 'mall': ''})

    print(f'[naver_slots] {len([s for s in naver_slots if s["image_url"]])}개 이미지 확보')

    # ★ naver_slots 확정 후 더보기 캐시 저장! (naver_api.py 담당!)
    _locals = locals()
    if '_pending_cache_key' in _locals and '_pending_priced' in _locals:
        # ★ 더보기 저장 전 악세서리/개모차 필터!
        _MORE_FILTER_KW = ['커버', '패드', '천갈이', '덮개', '방석', '블랭킷', '보호대',
            '받침대', '거치대', '홀더', '파우치', '케이스', '스탠드', '브래킷',
            '쿠션', '목쿠션', '시트커버', '라이너', '장난감', '스티어링']
        _MORE_PET_KW = ['강아지', '애견', '반려동물', '펫', '개모차', '고양이', '반려견']
        _before = len(_pending_priced)
        _pending_priced = [(p, prod) for p, prod in _pending_priced
            if not any(kw in prod.get('name','') for kw in _MORE_FILTER_KW)
            and not any(kw in prod.get('name','') for kw in _MORE_PET_KW)]
        _filtered = _before - len(_pending_priced)
        if _filtered:
            print(f'[더보기필터] {_filtered}개 악세서리/개모차 제거!')
        
        from naver_api import save_more_cache
        _shown_names = {s.get('name', '')[:20] for s in naver_slots if s.get('name')}
        _shown_urls  = {s.get('product_url', '') for s in naver_slots if s.get('product_url')}
        save_more_cache(
            cache_store=_MORE_CACHE,
            cache_key=_pending_cache_key,
            priced=_pending_priced,
            grade_range=_pending_grade_range,
            shown_names=_shown_names,
            shown_urls=_shown_urls,
            grade=_grade,
            selections=selections,
            product_name=session.get('product_name', ''),
            cache_ttl=_MORE_CACHE_TTL,
            lost_review_slots=_lost_review,  # ★ 탈락 슬롯 전달!
        )
        session['more_cache_key'] = _pending_cache_key

    # ★ 동적 유효 쿼리 추출 (네이버 실제 제품 제목 기반)
    _valid_query = raw_product
    try:
        _titles = [rp["name"] for rp in real_products[:5] if rp.get("name")]
        if _titles and not _single_mode:
            _title_text = "\n".join(_titles)
            _user_sel = []
            for part in selections.split():
                if ":" in part:
                    k, v = part.split(":", 1)
                    if k not in ["가격", "E", "직접입력"] and v:
                        _user_sel.append(v)
            _sel_str = ", ".join(_user_sel)
            _valid_prompt = (
                f"아래는 네이버 쇼핑 실제 제품 제목들:\n{_title_text}\n\n"
                f"사용자 선택 조건: {_sel_str}\n"
                f"기본 제품: {raw_product}\n\n"
                "제품 제목에 자주 나오는 키워드만 골라서 검색 쿼리를 만들어주세요.\n"
                "규칙: 제목에 없는 추상적 키워드 제외(푹신함/직선형/커버세탁 등), 최대 5단어, 쿼리만 출력"
            )
            _valid_query = call_llm(_valid_prompt, max_tokens=30).strip().split("\n")[0]
            print(f"[동적쿼리] {_valid_query}")
    except Exception as e:
        print(f"[동적쿼리오류] {e}")
        _valid_query = raw_product

    # 실제 제품 정보를 LLM에 전달할 텍스트 생성
    real_products_hint = ''
    for i, slot in enumerate(naver_slots[:3]):
        if slot.get('name'):
            real_products_hint += f'{i+1}. {slot["name"]} / {slot["price"]} / {slot["mall"]}\n'
    if real_products_hint:
        price_range_note = f' ({_actual_price_range})' if _actual_price_range else ''
        real_products_hint = f'\n【실제 네이버 쇼핑 제품】{_grade}{price_range_note} 기준:\n{real_products_hint}'

    # 가격 조건 → LLM 참고용 (필터링은 이미 4분위로 완료)
    _price_naver = {'저가':'저렴한', '중가':'합리적인', '고가':'고급', '최고가':'프리미엄'}
    _price_naver_kw = _price_naver.get(_grade, '')
    _price_rule = f'\n참고: [{_grade}] 가격대 제품들입니다. (4분위 필터 완료)' if _grade else ''
    if _price_naver_kw and _price_naver_kw not in keyword:
        keyword = f'{_price_naver_kw} {keyword}'

    # 추천 개수 결정
    if _single_mode:
        _max_products = 1
        print(f'[추천개수] 단일 제품 모드 → 1개만 추천')
    else:
        _max_products = len([s for s in naver_slots if s.get('image_url')])
        _max_products = max(1, _max_products)
        print(f'[추천개수] 이미지 {_max_products}개 확보 → {_max_products}개 추천')

    # ★ 카드 병렬 생성 (1초 간격으로 LLM 3명 동시 투입!)
    # 1순위: 즉시 시작 / 2순위: 1초 후 / 3순위: 2초 후
    # 각자 완성되면 즉시 card_queue 전송!
    import json as _json
    import re as _re_json
    import threading as _threading
    import time as _time

    _all_products = [None] * _max_products  # 순서 보장용 (인덱스로 저장)
    _notice_val = ''
    _condition_desc_val = ''
    _match_keywords = []

    # ── 카드 1개 처리 내부 함수 ──
    def _process_card(_ci):
        nonlocal _notice_val, _condition_desc_val, _match_keywords
        if _ci >= len(naver_slots):
            return
        _slot = naver_slots[_ci]
        _slot_hint = f'{_slot["name"]} / {_slot.get("price","?")}' if _slot.get('name') else ''
        _is_first = (_ci == 0)
        _notice_field = '"notice": "제약 안내 한 줄 (없으면 빈 문자열)",' if _is_first else '"notice": "",'
        _cond_field = '"condition_desc": "선택 조건 중 소재/기능 핵심 한 줄 설명 (예: 아쿠아텍스는 방수 기능이 있는 프리미엄 패브릭입니다, 없으면 빈 문자열)",' if _is_first else '"condition_desc": "",'

        _single_prompt = f"""사용자 조건: {selections}{_price_rule}
{f"추가 요청: {extra}" if extra else ""}
찾는 제품: {raw_product}
【이 제품 ({_ci+1}순위)】: {_slot_hint}
【자동 알고 사세요】
{auto_cautions_str}

제품 1개를 JSON으로만 출력:

{{{_notice_field}
{_cond_field}
"products": [
  {{
    "rank": {_ci+1},
    "name": "제품명",
    "price": "가격대",
    "match_score": 85,
    "image_url": "",
    "product_url": "",
    "match_conditions": ["충족 조건1", "충족 조건2"],
    "fail_conditions": ["미충족 조건"],
    "reviews": [
      {{"summary": "20자 이내 핵심요약", "text": "80자 이내 후기", "source": "출처명", "icon": "💚"}}
    ],
    "reason": "이런 이유로 사세요 (50자 이내, 핵심 구매 이유)",
    "cautions": ["알고 사세요1"],
    "search_query": "네이버 검색어"
  }}
]}}

규칙: 반드시 JSON만 출력, 코드블록 절대 금지, 제품 1개만, 광고 금지
reviews 최대 3개, text 80자 이내, cautions 최대 2개, url 필드 없음
auto_cautions가 있으면 cautions 배열에 반드시 포함
첫 글자는 반드시 {{ 로 시작

★★ 절대 금지 (위반 시 신뢰 붕괴!):
- 후기에 없는 내용을 사실처럼 서술 금지!
- TV광고, 유명한, 인기 있는 등 검증 불가 표현 금지!
- 사용자 직접입력 조건을 제품 특징인 것처럼 reason에 서술 금지!
- 후기 없으면 reviews는 빈 배열 [], reason은 후기가 부족해 확인이 어려워요"""

        # ★ 스트리밍 or 일반 호출
        _raw_card = ''
        if card_queue:
            from main import call_llm_stream
            for _tok in call_llm_stream(_single_prompt, system=SYSTEM_RULES, max_tokens=2000):
                card_queue.put({'type': 'token', 'text': _tok, 'rank': _ci + 1})
                _raw_card += _tok
        else:
            _raw_card = call_llm(_single_prompt, system=SYSTEM_RULES, use_sonnet=False, max_tokens=2000)

        # 카드 파싱
        _prod = {}
        try:
            _rc = _raw_card.strip()
            if '```' in _rc:
                for _pt in _rc.split('```'):
                    _pt = _pt.strip()
                    if _pt.startswith('json'): _pt = _pt[4:].strip()
                    if _pt.startswith('{'): _rc = _pt; break
            if not _rc.startswith('{'):
                _s = _rc.find('{')
                if _s != -1: _rc = _rc[_s:]
            if not _rc.rstrip().endswith('}'):
                _lb = _rc.rfind('}')
                if _lb != -1:
                    _rc = _rc[:_lb+1]
                    _rc += '}' * max(0, _rc.count('{') - _rc.count('}'))
            _card_data = _json.loads(_rc)
            if _is_first:
                _notice_val = _card_data.get('notice', '')
                _condition_desc_val = _card_data.get('condition_desc', '')
            _prod = (_card_data.get('products') or [{}])[0]
            _prod['rank'] = _ci + 1
        except Exception as _pe:
            print(f'[카드파싱오류] rank={_ci+1} {_pe}')
            _prod = {'rank': _ci+1, 'name': '', 'price': '', 'reviews': [], 'reason': '', 'cautions': []}

        # ★ 1:1 매칭 (기존 로직 그대로)
        PLATFORM_NAMES = ['네이버', '쿠팡', 'G마켓', '옥션', '11번가', '위메프', '티몬', '롯데온', '카카오']
        real_name = _slot.get('name', '')
        slot_mall = _slot.get('mall', '')
        slot_brand = _slot.get('brand', '')
        slot_maker = _slot.get('maker', '')
        if any(p in slot_mall for p in PLATFORM_NAMES): slot_mall = ''
        if slot_mall:
            slot_mall = re.sub(r'(mall|몰|Mall)$', '', slot_mall).strip()
        name_first = real_name.split()[0] if real_name else ''
        EVENT_PATTERNS = ['(N', '[N', '(스툴', '[증정', '(증정', '(+', '[+', '(사은', '(쿠폰']
        name_first_invalid = (
            name_first.startswith('(') or name_first.startswith('[') or
            any(name_first.startswith(p) for p in EVENT_PATTERNS)
        )
        if name_first_invalid:
            _cn = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', real_name).strip()
            name_first = _cn.split()[0] if _cn.split() else ''
            print(f'[브랜드정제] 이벤트문구 제거 → "{name_first}"')
        prod_brand_filter = slot_brand or slot_maker or slot_mall or name_first
        print(f'[브랜드추출] brand={slot_brand} maker={slot_maker} 제품첫단어={name_first} mall={slot_mall} → {prod_brand_filter}')

        if _single_mode:
            prod_search = raw_product
            prod_brand_filter = _brand_filter or prod_brand_filter
        else:
            if real_name:
                prod_search = ' '.join(real_name.split()[:4])
            elif _valid_query:
                prod_search = _valid_query
            else:
                prod_search = ' '.join((_prod.get('name', raw_product)).split()[:3])

        print(f'[1:1매칭] 검색어: {prod_search} / 브랜드필터: {prod_brand_filter}')

        # ★ 후기 수집 전에 이미지/이름/가격 즉시 주입 + header 전송!
        if _slot.get('image_url'):
            _prod['image_url'] = _slot['image_url']
            print(f'[이미지주입] {_slot["image_url"][:60]}')
        if _slot.get('product_url'): _prod['product_url'] = _slot['product_url']
        if _slot.get('name'): _prod['name'] = _slot['name']
        if _slot.get('price'): _prod['price'] = _slot['price']
        _prod['from_review'] = _slot.get('from_review', False)
        _prod['original'] = _slot.get('original', False)
        _prod['direct_blog_verified'] = _slot.get('direct_blog_verified', False)
        print(f'[뱃지전달] {_slot.get("name","")[:20]} from_review={_prod["from_review"]}')

        if card_queue:
            card_queue.put({
                'type': 'header',
                'rank': _ci + 1,
                'name': _prod.get('name', ''),
                'price': _prod.get('price', ''),
                'image_url': _prod.get('image_url', ''),
                'product_url': _prod.get('product_url', ''),
                'cautions': _prod.get('cautions', []),
                'from_review': _prod.get('from_review', False),
                'original': _prod.get('original', False),
                'notice': _notice_val if _ci == 0 else '',
                'condition_desc': _condition_desc_val if _ci == 0 else '',
                'grade': _grade,
                'more_cache_key': session.get('more_cache_key', ''),
                'match_keywords': [],
            })
            print(f'[헤더전송] {_ci+1}순위 LLM 완성 즉시! (후기 수집 전)')

        # 후기 수집 (header 이미 전송됨!)
        prod_reviews = _collect_blog_reviews(prod_search, selections, extra, brand_filter=prod_brand_filter)
        if len(prod_reviews) < 3:
            print(f'[후기부족] {prod_brand_filter} → 필터 완화 재시도')
            all_reviews = _collect_blog_reviews(prod_search, selections, extra, brand_filter='')
            _brand_kws = [w for w in [prod_brand_filter] + prod_search.split()[:2] if w and len(w) > 1]
            matched = [r for r in all_reviews
                if any(kw in r.get('text','') or kw in r.get('title','') or kw in r.get('bloggername','')
                       for kw in _brand_kws)]
            if matched:
                prod_reviews = matched
                print(f'[후기완화] 브랜드필터 → {len(prod_reviews)}개')
            else:
                print(f'[후기완화] 매칭없음 → 기존 {len(prod_reviews)}개 유지')
        print(f'[제품별후기] {prod_search} → {len(prod_reviews)}개')

        # ★ 자체몰 리뷰 수집 (한샘/vreview/크리마 자동 분기!)
        try:
            from naver_api import get_brand_mall_reviews, BRAND_REVIEW_API
            import re as _re_pid

            # 브랜드가 매핑에 있는지 확인
            _matched_brand = None
            for _bk in BRAND_REVIEW_API:
                if _bk in prod_brand_filter or prod_brand_filter in _bk:
                    _matched_brand = _bk
                    break

            if _matched_brand:
                # ★ 패스워드 자동 추출!
                from naver_api import auto_find_product_id, BRAND_REVIEW_API
                _official_url = _prod.get('product_url', '')

                # naver_slots에서 더 좋은 URL 찾기
                for _sl in naver_slots:
                    _sl_url = _sl.get('product_url', '')
                    if any(d in _sl_url for d in ['hanssem', 'livart', 'jacksonchameleon', 'topten']):
                        _official_url = _sl_url
                        break

                _pid = auto_find_product_id(_matched_brand, prod_search, _official_url)

                # 못 찾으면 테스트용 goods_no 사용!
                if not _pid:
                    _api_info = BRAND_REVIEW_API.get(_matched_brand, {})
                    _pid = _api_info.get('test_goods_no', '')
                    if _pid:
                        print(f'[패스워드] {_matched_brand} → 테스트 goods_no={_pid} 사용')

                print(f'[패스워드결과] {_matched_brand} → {_pid}')

                if _pid:
                    _mall_reviews = get_brand_mall_reviews(_matched_brand, _pid, limit=100)
                    if _mall_reviews:
                        _crawl_formatted = [
                            {
                                'text': r['text'][:200],
                                'full_text': r['text'][:500],
                                'postdate': r.get('date', '').replace('-', '') or '',
                                'bloggername': r.get('source', '자체몰 구매자'),
                                'url': '',
                                'source': r.get('source', '자체몰 리뷰'),
                            }
                            for r in _mall_reviews if r.get('text')
                        ]
                        prod_reviews = _crawl_formatted + prod_reviews  # ★ 자체몰 리뷰 우선!
                        print(f'[자체몰리뷰] {_matched_brand} +{len(_crawl_formatted)}건 → 총{len(prod_reviews)}건')
                else:
                    print(f'[자체몰스킵] {prod_brand_filter} → product_id 추출 실패')
            else:
                print(f'[자체몰스킵] {prod_brand_filter} → 매핑 없음')

        except Exception as _ce:
            print(f'[자체몰오류] {_ce}')

        # ★ 제품 센서 (trust_layer) — 버려지던 postdate/full_text 활용!
        try:
            from trust_layer import calculate_T, get_badge
            _trust = calculate_T(prod_reviews)
            _badge = get_badge(_trust)
            _prod['trust'] = _trust
            _prod['trust_badge'] = _badge
            print(f'[제품센서] {_ci+1}순위 → {_badge} T={_trust["T_final"]} ({_trust["months"]}개월/{_trust["total_posts"]}건)')
            if card_queue and _badge:
                card_queue.put({
                    'type': 'trust',
                    'rank': _ci + 1,
                    'badge': _badge,
                    'months': _trust['months'],
                    'total_posts': _trust['total_posts'],
                    'rebuy_count': _trust['rebuy_count'],
                    'q_count': _trust['q_count'],
                    'neg_count': _trust['neg_count'],
                    'penalty': _trust['penalty'],
                    'T_final': _trust['T_final'],
                })
                print(f'[센서전송] {_ci+1}순위 [{_badge}]')
        except Exception as _te:
            print(f'[제품센서오류] {_te}')

        # 픽코 평점/목소리/총평/감성 (기존 로직 그대로)
        from review_builder import extract_match_keywords, build_product_features, build_fit_or_not
        _match_keywords = extract_match_keywords(selections, _direct_input)
        print(f'[매칭키워드] {_match_keywords}')

        # ★ 이 제품의 특징 - 기존 prod_reviews에서 바로 추출! (새 쿼리 없음)
        _features = build_product_features(prod_reviews, real_name or raw_product, call_llm, direct_input=_direct_input or '')
        _prod['features'] = _features
        if card_queue and _features:
            card_queue.put({'type': 'features', 'rank': _ci+1, 'data': _features})
            print(f'[특징전송] {_ci+1}순위 {len(_features)}개')

        # ★ 픽코 평점
        _prod['picko_ratings'] = _build_picko_ratings(prod_reviews, selections, extra)
        if card_queue:
            card_queue.put({'type': 'rating', 'rank': _ci+1, 'data': _prod['picko_ratings']})
            print(f'[별점전송] {_ci+1}순위')


        # ★ 3단계: 사용자 목소리 (공식몰 3개 + 블로그 3개 분리!)
        _r1_reviews   = [r for r in prod_reviews if r.get('source', '').startswith('R1') or r.get('source', '').startswith('R2')]
        _blog_reviews = [r for r in prod_reviews if not (r.get('source', '').startswith('R1') or r.get('source', '').startswith('R2'))]

        _official_voices = []
        _blog_voices     = []

        if _r1_reviews:
            _official_voices = _build_user_voices(
                _r1_reviews, extra, call_llm,
                brand_filter=prod_brand_filter,
                match_keywords=_match_keywords,
                user_context=_user_context,
            )
            print(f'[공식몰목소리] {len(_official_voices)}개')

        _blog_voices = _build_user_voices(
            _blog_reviews, extra, call_llm,
            brand_filter=prod_brand_filter,
            match_keywords=_match_keywords,
            user_context=_user_context,
        )
        print(f'[블로그목소리] {len(_blog_voices)}개')

        # 구조: {'official': [...], 'blog': [...]}
        _prod['user_voices'] = {
            'official': _official_voices,  # 공식몰 (없으면 [])
            'blog':     _blog_voices,      # 블로그/카페
        }
        if card_queue:
            card_queue.put({'type': 'voices', 'rank': _ci+1, 'data': _prod['user_voices']})
            print(f'[후기전송] {_ci+1}순위')

        # ★ 5단계: 좋다는 말 / 아쉽다는 말
        _pros, _cons, _one_line, _price_info, _situations, _long_term = _build_pros_cons_oneline(
            real_name or raw_product, prod_reviews, selections, call_llm
        )
        _prod['pros']          = _pros
        _prod['cons']          = _cons
        _prod['prod_reviews_cache'] = prod_reviews[:10]  # 맥락 대화용
        _prod['price_info']    = _price_info

        # ★ 6단계: 맞아요/아닌분/한줄평 [통합]
        _fit_data = build_fit_or_not(prod_reviews, real_name or raw_product, selections, call_llm)
        _prod['fit']      = _fit_data.get('fit', _situations)       # 새 함수 우선, 없으면 기존
        _prod['not_fit']  = _fit_data.get('not_fit', [])
        _prod['one_line'] = _fit_data.get('one_line', _one_line)

        if card_queue and (_pros or _cons or _price_info or _prod['fit'] or _prod['not_fit']):
            card_queue.put({
                'type':      'pros_cons',
                'rank':      _ci+1,
                'pros':      _pros,
                'cons':      _cons,
                'one_line':  _prod['one_line'],
                'price_info': _price_info,
                'situations': _prod['fit'],
                'not_fit':   _prod['not_fit'],
                'long_term': '',   # 삭제
            })
            print(f'[픽코분석전송] {_ci+1}순위 pros={len(_pros)} cons={len(_cons)}')

        _all_products[_ci] = _prod

        # ★ 카드 완성 신호
        if card_queue:
            card_queue.put({
                'type': 'card',
                'rank': _ci + 1,
                'data': _prod,
            })
            print(f'[카드완성] {_ci+1}순위!')

    # ★ 스레드 1초 간격으로 시작! (LLM 3명 병렬 투입)
    _threads = []
    for _ci in range(_max_products):
        t = _threading.Thread(target=_process_card, args=(_ci,), daemon=True)
        t.start()
        _threads.append(t)
        if _ci < _max_products - 1:
            _time.sleep(1)  # ★ 1초 간격! Rate Limit 방지

    # 모든 카드 완료 대기
    for t in _threads:
        t.join(timeout=90)

    # 순서 정렬 (None 제거)
    _all_products_ordered = [p for p in _all_products if p is not None]

    # ★ 전체 결과 조합 → PICKO_RESULT
    rec_data = {
        'notice': _notice_val,
        'condition_desc': _condition_desc_val,
        'products': _all_products_ordered,
        'grade': _grade,
        'more_cache_key': session.get('more_cache_key', ''),
        'match_keywords': _match_keywords,
    }
    # constraint_notice → notice 필드에 병합
    if constraint_notice and not rec_data.get('notice'):
        rec_data['notice'] = constraint_notice

    json_str = _json.dumps(rec_data, ensure_ascii=False)
    json_str = _re_json.sub(r'[\x08\x0b\x0c\x0e-\x1f]', '', json_str)
    result = 'PICKO_RESULT:' + json_str
    print('[추천결과] 병렬 카드 생성 완료')

    # ★ 마지막 추천 제품 세션 저장 (맥락 대화용)
    def _get_pct(ratings, label):
        return next((r.get('pct', 0) for r in ratings if label in r.get('label', '')), 0)

    _context_key = session.get('more_cache_key', '') or str(id(_all_products_ordered))
    _context_data = [
        {
            'rank': i + 1,
            'name': p.get('name', ''),
            'price': p.get('price', ''),
            'pros': p.get('pros', []),
            'cons': p.get('cons', []),
            'quality_pct': _get_pct(p.get('picko_ratings', []), '품질'),
            'satisfaction_pct': _get_pct(p.get('picko_ratings', []), '만족'),
            'sensor': p.get('sensor_tag', ''),
            'reviews': [r.get('text', '')[:120] for r in (p.get('prod_reviews_cache') or [])[:8]],
            'voices': [
                {
                    'text': v.get('text', '')[:80],
                    'source': v.get('source') or v.get('bloggername', ''),
                    'url': v.get('url', '') or v.get('link', '')
                }
                for v in list(p.get('user_voices', {}).get('blog', []))[:2]
            ]
        }
        for i, p in enumerate(_all_products_ordered[:3])
    ]
    session['last_products'] = _context_data
    session['context_key'] = _context_key
    _CONTEXT_CACHE[_context_key] = _context_data
    print(f'[맥락캐시] 저장 완료 key={_context_key[:20]}')

    # ★ 픽코 총평 비평 (3개 카드 완료 후 - 각 카드마다 하나씩)
    _critiques = []
    if card_queue and len(_all_products_ordered) >= 2:
        from review_builder import build_picko_critique
        _critiques = build_picko_critique(_all_products_ordered, _user_context, call_llm)
        if _critiques:
            print(f'[총평비평] {len(_critiques)}개 생성')

    # 스트리밍 모드는 done 신호 전송
    if card_queue:
        card_queue.put({
            'type': 'done',
            'critiques': _critiques,
            'session_update': {
                'last_products': session.get('last_products', []),
                'context_key': session.get('context_key', ''),
                'user_context': _user_context
            }
        })

    return result


def get_more_recommendations(cache_key: str, grade: str, count: int = 3) -> dict:
    """더보기 버튼 - 캐시에서 다음 N개 반환 (API 재호출 없음)
    ★ 교차 구간 중복제거: 한번 출현하면 다른 구간에서 제외!"""
    # 만료 캐시 정리
    now = time.time()
    expired = [k for k, v in _MORE_CACHE.items() if v['expires'] < now]
    for k in expired:
        del _MORE_CACHE[k]

    entry = _MORE_CACHE.get(cache_key)
    if not entry:
        return {'error': '캐시 만료', 'products': []}

    pools = entry['pools']
    shown = entry.get('shown', {})
    # ★ 전체 구간 통합 중복제거 set
    if 'seen_names' not in entry:
        entry['seen_names'] = set()
    seen_names = entry['seen_names']

    pool = pools.get(grade, [])
    start = shown.get(grade, 3)  # 첫 3개는 이미 추천됨

    # ★ 중복제거 적용해서 다음 제품 수집
    next_products = []
    idx = start
    while len(next_products) < count and idx < len(pool):
        p = pool[idx]
        name_key = p.get('name', '')[:20]
        if name_key not in seen_names:
            next_products.append(p)
            seen_names.add(name_key)
        idx += 1

    entry['shown'][grade] = idx

    if not next_products:
        return {'error': '더 이상 제품 없음', 'products': [], 'grade': grade}

    # 간단한 제품 정보 반환 (LLM 리뷰 없이)
    result = []
    for p in next_products:
        result.append({
            'name': p.get('name', ''),
            'price': p.get('price', ''),
            'image_url': p.get('image_url', ''),
            'product_url': p.get('product_url', ''),
            'mall': p.get('mall', ''),
        })

    remaining = max(0, len(pool) - idx)
    print(f'[더보기] {grade} → {len(result)}개 반환 (남은:{remaining}개)')
    return {
        'products': result,
        'grade': grade,
        'remaining': remaining,
        'actual_range': f'{pool[start].get("price","?") if start < len(pool) else ""}',
    }


