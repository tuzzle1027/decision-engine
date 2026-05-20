# ===============================
# naver_api.py
# 이미지/쇼핑 검색 API 모듈
# main.py에서 분리
# ===============================
#
# 포함:
#   _JOBS / _DESIRE_CACHE     백그라운드 캐시
#   start_desire_prefetch()   욕망보드 사전수집
#   search_google_images()    구글 이미지
#   search_naver_images()     네이버 이미지
#   search_naver_shopping_images() 네이버 쇼핑
#   verify_images_batch()     GPT Vision 검증
#   search_desire_board_images() 욕망보드 이미지
#   search_instagram_images() 인스타 이미지
# ===============================

import os
import json
import re
import time
import threading
import urllib.request
import concurrent.futures

OPENAI_API_KEY      = os.environ.get('OPENAI_API_KEY', '')

# ── 메모리 캐시 ──
# 서버 재시작 시 사라지지만 같은 세션 내 중복 API 호출 방지
_CACHE = {}           # 범용 캐시 {key: (값, 만료시간)}
_IS_DEV = os.environ.get('FLASK_ENV', 'production') == 'development'
_CACHE_TTL = 1 if _IS_DEV else 600  # 개발: 1초 / 운영: 10분

# ★ 마음 상황판 전역 컨텍스트 (routes.py에서 설정 → 스키마에서 참조)
_MIND_CONTEXT = ''

def set_mind_context(text):
    global _MIND_CONTEXT
    _MIND_CONTEXT = text or ''


# ★ 마음 상황판용: 네이버 제목 200개 수집
def fetch_titles_for_mind(product, limit=200):
    """마음 Q1 생성용 네이버 제목 수집"""
    import urllib.parse as _up
    import urllib.request
    titles = []
    try:
        _headers = {
            'X-Naver-Client-Id': NAVER_CLIENT_ID,
            'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
        }
        _display = min(limit, 100)
        _starts = [1] if limit <= 100 else [1, 101]
        for _start in _starts:
            try:
                _q = _up.quote(product)
                _req = urllib.request.Request(
                    f'https://openapi.naver.com/v1/search/shop?query={_q}&display={_display}&start={_start}&sort=sim',
                    headers=_headers
                )
                _res = urllib.request.urlopen(_req, timeout=5)
                _items = json.loads(_res.read()).get('items', [])
                for _item in _items:
                    _t = re.sub(r'<[^>]+>', '', _item.get('title', ''))
                    if _t: titles.append(_t)
            except:
                break
        print(f'[마음Q1] 네이버 {len(titles)}개 제목 수집')
    except Exception as e:
        print(f'[마음Q1네이버오류] {e}')
    return titles


# ★ 마음 상황판용: 제목 빈도 키워드 추출
def analyze_mind_keywords(titles, product=''):
    """200개 제목에서 빈도 높은 키워드 추출 → 숫자로!"""
    if not titles:
        return ''
    # 불용어 (제품명 자체, 일반 단어)
    stopwords = {'추천', '인기', '최저가', '무료배송', '할인', '특가', '사은품',
                 '정품', '당일발송', '국내', '해외', '브랜드', '신상', '신제품',
                 '세트', '단품', '개', '팩', '박스', '세일', '쿠폰', '리뷰',
                 product}
    # 제목에서 키워드 추출
    word_count = {}
    for title in titles:
        # 한글 단어 + 영문 단어 + 숫자단위 추출
        words = re.findall(r'[가-힣]{2,}|[a-zA-Z]{2,}\d*', title)
        seen = set()
        for w in words:
            w_lower = w.lower()
            if w_lower in stopwords or w in stopwords:
                continue
            if len(w) < 2:
                continue
            if w not in seen:
                word_count[w] = word_count.get(w, 0) + 1
                seen.add(w)
    # 빈도순 정렬, 상위 20개
    sorted_words = sorted(word_count.items(), key=lambda x: -x[1])
    
    # ★ 비슷한 키워드 그룹핑! (편중 방지)
    # 1. 포함 관계 제거: "휴대용유모차"는 "휴대용"에 포함 → 제거
    filtered = []
    for w, c in sorted_words:
        is_subset = False
        for fw, fc in filtered:
            if w in fw or fw in w:
                is_subset = True
                break
        if not is_subset:
            filtered.append((w, c))
    
    top = filtered[:15]
    # "접이식(30개), 경량(20개)" 형식
    result = ', '.join([f'{w}({c}개)' for w, c in top if c >= 3])
    print(f'[마음빈도] {product}: {result[:100]}')
    return result

def _cache_get(key: str):
    """캐시에서 값 가져오기 (만료되면 None)"""
    if key in _CACHE:
        val, expires = _CACHE[key]
        if time.time() < expires:
            return val
        del _CACHE[key]
    return None

def _cache_set(key: str, val, ttl: int = _CACHE_TTL):
    """캐시에 값 저장"""
    _CACHE[key] = (val, time.time() + ttl)

# 가격 트리거 항목 (이 항목 선택 시 가격 동적 업데이트)
PRICE_TRIGGER_LABELS = [
    '소재', '상판재질', '가죽종류',           # 소재류
    '폭', '사이즈', '크기', '상판크기',        # 크기류
    '구성', '매트리스', '의자포함',            # 포함여부류
    '형태', '수납형태',                       # 형태류
    '헤드유무', '헤드기능',                   # 침대 헤드
    '매트리스종류',                           # 매트리스 타입
]

def crawl_smartstore_tags(url: str) -> dict:
    """
    스마트스토어 상품 페이지에서 태그 추출
    종류/너비/단수/소재/형태/색상계열 등
    """
    import time
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9',
                'Referer': 'https://shopping.naver.com',
            }
        )
        res = urllib.request.urlopen(req, timeout=5)
        html = res.read().decode('utf-8', errors='ignore')

        # 태그 패턴 추출
        # "종류 : 책장단품", "너비 : 500mm" 형태
        ATTR_KEYS = ['종류', '너비', '단수', '소재', '형태', '색상계열',
                     '자재등급', '칸수', '특징', '원목종류', '사이즈',
                     '용량', '소비전력', '화면크기', '해상도', '무게',
                     '재질', '두께', '길이', '높이', '폭', '색상']

        tags = {}
        for key in ATTR_KEYS:
            # "종류 : 책장단품" or "종류: 책장단품" 패턴
            escaped = re.escape(key)
            pattern = escaped + r'\s*:\s*([^<"\n{}]{1,50})'
            match = re.search(pattern, html)
            if match:
                val = match.group(1).strip().rstrip(',').strip()
                if val and len(val) < 50:
                    tags[key] = val

        return tags
    except Exception as e:
        print(f'[태그크롤링오류] {url[:50]} → {e}')
        return {}


def get_board_pattern(product: str) -> str:
    """
    네이버 쇼핑 100개 분석 → 상황판 패턴 자동 생성
    캐시: 1시간 유지
    """
    # 제품명 정규화 (찾아줘/추천 등 제거)
    import re as _re2
    product = _re2.sub(r'\s*(찾아줘|찾아|추천해줘|추천해|알려줘|보여줘).*$', '', product).strip()
    if not product:
        return ''

    # ★ 마음 상황판으로 검색 쿼리 보강
    search_product = product
    if _MIND_CONTEXT:
        try:
            from main import call_llm
            _boost = call_llm(
                f'제품: {product}\n사용자정보: {_MIND_CONTEXT}\n'
                f'이 사용자에게 맞는 네이버 쇼핑 검색 키워드를 한 줄로 만들어. '
                f'키워드만 답해. 따옴표 없이.',
                max_tokens=20
            ).strip().strip('"\'')
            if _boost and len(_boost) < 30:
                search_product = _boost
                print(f'[마음쿼리보강] {product} → {search_product}')
        except Exception as e:
            print(f'[마음쿼리보강오류] {e}')

    # ★ 캐시 키에 마음 정보 포함 (마음 다르면 다른 상황판)
    _mind_hash = hash(_MIND_CONTEXT) if _MIND_CONTEXT else ''
    cache_key = f'board_pattern:{search_product}:{_mind_hash}'
    cached = _cache_get(cache_key)
    if cached:
        print(f'[패턴캐시] {search_product} → 캐시 히트!')
        return cached

    print(f'[패턴분석] {search_product} 네이버 분석 시작...')

    def _naver_search(query_str, display=100):
        """네이버 쇼핑 검색 내부 함수"""
        try:
            import urllib.parse as _up
            q = _up.quote(query_str)
            req = urllib.request.Request(
                f'https://openapi.naver.com/v1/search/shop?query={q}&display={display}&sort=sim',
                headers={
                    'X-Naver-Client-Id': NAVER_CLIENT_ID,
                    'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
                }
            )
            res = urllib.request.urlopen(req, timeout=5)
            return json.loads(res.read()).get('items', [])
        except Exception as e:
            print(f'[검색오류] {query_str}: {e}')
            return []

    # 1. 네이버 쇼핑 검색 (스마트 확장)
    items = _naver_search(search_product)

    # 결과 적으면 연관키워드로 재검색
    if len(items) < 10:
        print(f'[검색확장] {search_product} → 결과 {len(items)}개, 연관키워드로 재검색')
        # 연관키워드 추출 (카테고리 제외)
        CATEGORY_WORDS = {'가구', '인테리어', '생활', '주방', '디지털', '패션', '스포츠', '도서'}
        related_queries = []
        # 제품명 단순화 (앞 키워드 제거)
        words = product.split()
        if len(words) > 1:
            related_queries.append(' '.join(words[1:]))  # 앞 단어 제거
            related_queries.append(' '.join(words[:-1]))  # 뒤 단어 제거
        # 유사어 매핑
        SIMILAR_MAP = {
            'TV장': ['거실장', 'TV거실장', '티비장'],
            'tv장': ['거실장', 'TV거실장'],
            '티비장': ['거실장', 'TV장'],
            '행거': ['의류행거', '옷걸이행거', '드레스행거'],
            '수납장': ['수납가구', '다용도수납장'],
            '책꽂이': ['책장', '북스탠드'],
            '옷걸이': ['행거', '의류행거'],
        }
        if product in SIMILAR_MAP:
            related_queries = SIMILAR_MAP[product] + related_queries

        for rq in related_queries[:3]:
            if not rq or rq == product:
                continue
            new_items = _naver_search(rq)
            if len(new_items) >= 10:
                print(f'[검색확장] {product} → "{rq}" 로 재검색 성공! ({len(new_items)}개)')
                items = new_items
                break

    if not items:
        return ''

    # 2. 다수결 카테고리 파악 → 처음부터 주요 카테고리만 사용
    from collections import Counter as _CatCounter
    cat_freq = _CatCounter(
        item.get('category1', '') for item in items
        if item.get('category1', '')
    )
    dominant_cat = cat_freq.most_common(1)[0][0] if cat_freq else ''
    dominant_ratio = cat_freq.most_common(1)[0][1] / len(items) if cat_freq else 0
    print(f'[카테고리분석] {product}: {dict(cat_freq.most_common(3))} → 주요: {dominant_cat}({dominant_ratio:.0%})')

    # 주요 카테고리가 40% 이상이면 처음부터 필터링
    if dominant_cat and dominant_ratio >= 0.4:
        items = [item for item in items if item.get('category1', '') == dominant_cat]
        print(f'[카테고리필터] {dominant_cat}만 사용 → {len(items)}개')

    # 2. 제목 + 가격 수집 + 스마트스토어 태그 크롤링
    titles = []
    prices = []
    all_tags = {}  # 태그 빈도 수집
    STOP_WORDS = {'찾아줘', '찾아', '추천', '알려줘', '보여줘', '제품', '상품', '구매', '선택'}
    core_keywords = [w for w in product.split() if len(w) >= 2 and w not in STOP_WORDS]
    # 복합어 분리 (회전책장→회전/책장, TV장→TV/장)
    expanded = []
    for kw in core_keywords:
        if len(kw) >= 4:
            for i in range(2, len(kw)-1):
                expanded.append(kw[:i])
                expanded.append(kw[i:])
        elif len(kw) >= 2:
            expanded.append(kw)
    # 1글자 이상 모든 분리어 추가
    for w in product.split():
        if len(w) >= 1:
            expanded.append(w)
    # 영문+한글 혼합어 분리 (TV장→TV/장, PC방→PC/방)
    for kw in list(core_keywords):
        eng_part = re.match(r'^([A-Za-z]+)', kw)
        if eng_part:
            kor_part = kw[eng_part.end():]
            if kor_part:
                expanded.append(eng_part.group())  # TV
                expanded.append(kor_part)           # 장
    core_keywords = list(set(core_keywords + expanded))
    
    # 스마트스토어 URL 최대 5개 태그 크롤링
    smartstore_count = 0
    import time as _time

    for item in items:
        title = item.get('title', '').replace('<b>', '').replace('</b>', '')
        title = re.sub(r'<[^>]+>', '', title).strip()

        if not title:
            continue

        # productType 필터링 (1=일반상품만, 2=중고, 3=렌탈, 4=해외직구 제외)
        product_type = item.get('productType', '1')
        if product_type not in ('1', ''):
            continue

        # 핵심 키워드가 제목에 포함된 것만 (정확도 향상)
        # 상위 30개는 무조건 포함, 나머지는 키워드 필터링
        if len(titles) >= 30 and core_keywords and not any(kw in title for kw in core_keywords):
            continue

        # 추가 정보 수집
        cat2 = item.get('category2', '')
        cat3 = item.get('category3', '')
        cat4 = item.get('category4', '')
        link = item.get('link', '')

        # 제목 + 추가 정보 합치기
        extra_info = ' '.join(filter(None, [cat2, cat3, cat4]))
        full_info = f"{title} {extra_info}".strip()
        titles.append(full_info)

        # 스마트스토어 태그 크롤링 (최대 5개)
        # 스마트스토어 태그 크롤링 비활성화 (Railway 403 차단)
        # TODO: 나중에 프록시 또는 다른 방법으로 해결
        # if smartstore_count < 5 and 'smartstore.naver.com' in link:
        #     tags = crawl_smartstore_tags(link)

        lprice = item.get('lprice', '')
        if lprice and lprice.isdigit():
            prices.append(int(lprice))

    # title에서 연관 키워드 자동 추출 (연관검색어 역할)
    from collections import Counter as _Counter
    STOP_WORDS_KW = {'찾아줘','찾아','추천','알려줘','보여줘','제품','상품',
                     '구매','선택','무료','배송','할인','특가','정품','공식',
                     '세트','묶음','증정','이상','이하','포함','제외',
                     '브랜드','신상','인기','베스트','아동','주니어','가구','인테리어'}
    word_freq = _Counter()
    for t in titles:
        words = t.split()
        for w in words:
            w = w.strip('.,!?()[]{}"\'')
            if len(w) >= 2 and w not in STOP_WORDS_KW and not any(c.isdigit() for c in w[:1]):
                word_freq[w] += 1
    # 제품명 자체 제외
    for kw in core_keywords:
        word_freq.pop(kw, None)
    top_keywords = [w for w, c in word_freq.most_common(20) if c >= 2]
    print(f'[연관키워드] {product}: {top_keywords[:10]}')
    print(f'[패턴분석] {product} → {len(titles)}개 제목, {len(prices)}개 가격, {len(all_tags)}개 태그속성 수집')

    # 제목이 너무 적으면 LLM 호출 안 함
    # 제목 너무 적으면 → 연관키워드로 재검색
    if len(titles) < 10:
        print(f'[검색확장] {product} → 필터후 {len(titles)}개, 재검색 시도')
        SIMILAR_MAP = {
            'TV장': ['거실장', 'TV거실장', '티비장'],
            '티비장': ['거실장', 'TV장식장'],
            '행거': ['의류행거', '드레스행거'],
            '책꽂이': ['책장', '북스탠드'],
            '옷걸이': ['의류행거', '행거'],
            '수납장': ['수납가구', '다용도선반'],
            '협탁': ['사이드테이블', '베드테이블'],
            '장식장': ['거실장', '수납장식장'],
        }
        retry_queries = list(SIMILAR_MAP.get(product, []))
        # 단어 분리도 시도
        words = product.split()
        if len(words) > 1:
            retry_queries.append(' '.join(words[1:]))

        for rq in retry_queries[:3]:
            if not rq or rq == product:
                continue
            try:
                import urllib.parse as _up2
                q2 = _up2.quote(rq)
                req2 = urllib.request.Request(
                    f'https://openapi.naver.com/v1/search/shop?query={q2}&display=100&sort=sim',
                    headers={
                        'X-Naver-Client-Id': NAVER_CLIENT_ID,
                        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
                    }
                )
                res2 = urllib.request.urlopen(req2, timeout=5)
                new_items = json.loads(res2.read()).get('items', [])
                new_titles = []
                for item2 in new_items:
                    if item2.get('productType', '1') not in ('1', ''):
                        continue
                    t2 = item2.get('title', '').replace('<b>', '').replace('</b>', '')
                    t2 = re.sub(r'<[^>]+>', '', t2).strip()
                    if t2:
                        new_titles.append(t2)
                if len(new_titles) >= 10:
                    print(f'[검색확장] {product} → "{rq}" 성공! ({len(new_titles)}개)')
                    titles = new_titles
                    # 가격도 재수집
                    for item2 in new_items:
                        lp = item2.get('lprice', '')
                        if lp and lp.isdigit():
                            prices.append(int(lp))
                    break
            except Exception as e:
                print(f'[검색확장오류] {rq}: {e}')

    if len(titles) < 5:
        print(f'[패턴분석] {product} → 제목 너무 적음({len(titles)}개), 패턴 생성 불가')
        return ''

    # ★ 마음 상황판으로 제목 필터링 (마음에 맞는 제목만 남기기)
    if _MIND_CONTEXT and len(titles) >= 30:
        try:
            from main import call_llm as _mind_llm
            _filter_result = _mind_llm(
                f'Product: {search_product}\nUser: {_MIND_CONTEXT}\n'
                f'이 사용자에게 맞는 제품 제목에 포함될 키워드 5개만 콤마로 답해. 키워드만.',
                max_tokens=30
            ).strip()
            _filter_kws = [k.strip() for k in _filter_result.split(',') if k.strip() and len(k.strip()) >= 1]
            if _filter_kws:
                _filtered = [t for t in titles if any(kw in t for kw in _filter_kws)]
                if len(_filtered) >= 15:
                    print(f'[마음필터] {len(titles)}개 → {len(_filtered)}개 (키워드: {_filter_kws})')
                    titles = _filtered
                else:
                    print(f'[마음필터] 필터 후 {len(_filtered)}개 부족 → 전체 유지')
        except Exception as e:
            print(f'[마음필터오류] {e}')

    # 3. LLM(Haiku)으로 패턴 분석
    titles_text = '\n'.join(titles[:60])  # 60개만

    # 태그 데이터 정리 (빈도순)
    tag_summary = ''
    if all_tags:
        tag_lines = []
        for k, vals in all_tags.items():
            # 중복 제거 + 빈도순
            from collections import Counter
            freq = Counter(vals)
            top_vals = [v for v, _ in freq.most_common(6)]
            tag_lines.append(f'{k}: {" / ".join(top_vals)}')
        tag_summary = '\n\n[실제 상품 태그 데이터 - 이것을 최우선으로 사용]\n' + '\n'.join(tag_lines)
        print(f'[태그요약]\n{tag_summary}')

    # 가격 구간 계산
    price_hint = ''
    if prices:
        prices.sort()
        trim = max(1, len(prices) * 15 // 100)
        trimmed = prices[trim:-trim] if len(prices) > trim * 2 else prices
        if trimmed:
            # ★ 항상 저가/중가/고가/최고가로 통일! 실제 금액 사용 안 함
            price_hint = '저가 / 중가 / 고가 / 최고가'

    # 연관 키워드 힌트 생성
    keyword_hint = ''
    if top_keywords:
        keyword_hint = f'\n\n[연관 키워드 - 상황판 항목 참고용]\n{" / ".join(top_keywords[:15])}'

    # 마음 상황판 맥락
    mind_hint = ''
    if _MIND_CONTEXT:
        mind_hint = f'\n\n[★★★ 최우선: 사용자 마음 상황판]\n{_MIND_CONTEXT}\n→ 반드시 이 사용자의 사용 맥락에 맞게 옵션을 조정하세요!\n→ 빈도에 없어도 이 사용자에게 필요한 스펙 옵션은 추가하세요\n→ 이 사용자와 관련 없는 옵션은 줄이세요\n→ 예: 영상편집자면 GPU 옵션 세분화, 코딩 개발자면 RAM 64GB/외부 모니터 추가'

    prompt = f"""아래는 네이버 쇼핑에서 "{product}" 검색 결과입니다.{tag_summary}{keyword_hint}{mind_hint}

[제품명 목록]
{titles_text}

위 정보에서 패턴을 분석해서 구매 결정에 영향을 미치는 상황판을 만들어주세요.
태그 데이터가 있으면 태그를 최우선으로 사용하고, 제품명에서 추가 패턴을 보완하세요.

[핵심 원칙]
상황판 항목 = 구매 결정에 직접 영향을 미치는 요소만
→ 크기/인원수 (몇 명이 쓸 건가)
→ 소재 (관리 편의성, 내구성)
→ 핵심 기능 (펼침방식, 수납 등 구매 이유가 되는 것)
→ 색상
→ 가격

[절대 금지]
- 마크다운(#, **, ##) 사용 금지
- 색상 옵션에 패턴/무늬/브랜드명/기타 절대 금지: 무지개/체크/스트라이프/컬러/기타/기타색상 등
- 색상은 실제 색상명만: 화이트/블랙/베이지/우드/원목/투명/그레이/크림 등
- "기타" "기타색상" "기타색" "혼합" "믹스" 는 색상 옵션에 절대 포함 금지!
- 색상을 모르면 그냥 그 항목을 빼고 다른 항목을 추가할 것
- 제품 카테고리명을 옵션으로 넣기 금지 (예: 소파베드 항목에 "소파베드" 옵션 금지)
- 브랜드/스타일/감성 같은 애매한 항목 금지
- 마감/오일마감/내추럴 같은 전문 제조 용어 금지 (일반 소비자가 모름)
- 혼합/복합 같은 애매한 소재 금지
- 제품 자체 카테고리를 소재/형태 옵션으로 쓰지 말 것
- 중복 의미 항목 금지 (기능과 형태가 같으면 하나로)
- 감으로 추가 금지 → 반드시 제품명에 나오는 것만

[형식 규칙]
- 반드시 아래 형식만 출력 (다른 텍스트 절대 없이)
- 옵션 구분: 반드시 ' / ' (슬래시)
- 항목명(대괄호 안)에 공백 금지: [높이조절기능] O / [높이조절 기능] X
- 3~5개 항목

형식:
[항목명1]
옵션1 / 옵션2 / 옵션3

[항목명2]
옵션1 / 옵션2 / 옵션3

[색상] ← 반드시 포함! 제품명에 색상이 보이면 추출, 없으면 주요 색상 추정
화이트 / 베이지 / 기타 (예시 - 실제 데이터 기반으로)

[가격] ← 반드시 마지막에 포함! 절대 생략 금지
{price_hint if price_hint else '저가 / 중가 / 고가 / 최고가'}

[E 직접입력]
원하는 조건을 자유롭게 입력하세요"""

    try:
        body = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 500,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01'
            },
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=10)
        result_data = json.loads(res.read())
        board_text = result_data['content'][0]['text'].strip()
        print(f'[패턴분석] {product} 상황판 생성 완료!')
        print(f'[패턴결과]\n{board_text}')

        # 캐시 저장 (1시간)
        _cache_set(cache_key, board_text, ttl=600)  # 10분 캐시
        return board_text

    except Exception as e:
        print(f'[패턴분석오류] LLM 실패: {e}')
        return ''


def get_price_range_by_selections(product: str, selections: dict) -> list:
    """
    선택된 조합으로 동적 가격 구간 계산
    예: product='옷장', selections={'소재':'원목', '폭':'1600'}
    → '원목 옷장 1600' 으로 네이버 검색 → 가격 구간
    캐시: 5분 유지
    """
    if not product:
        return []

    # 가격에 영향 주는 선택값만 추출
    # 의미없는 단독값 → label+value 합성 (예: 매트리스+포함 → 매트리스포함)
    # 특별 변환 규칙 (label+value → 실제 네이버 검색어)
    SPECIAL_CONVERT = {
        ('매트리스', '포함'):        '매트리스세트',
        ('매트리스', '별도구매'):     '프레임',
        ('의자포함', '포함'):         '의자포함',
        ('의자포함', '별도구매'):      '',
        ('헤드유무', '헤드있음'):      '헤드형',
        ('헤드유무', '헤드없음'):      '헤드리스',
        ('헤드기능', '기본형'):        '',   # 기본형은 제외
        ('수납형태', '없음'):          '',   # 수납없음 제외
        ('높이조절방식', '일반형'):      '',          # 일반형 = 그냥 책상 (저가)
        ('높이조절방식', '수동'):          '높이조절책상',  # 성인용 높이조절
        ('높이조절방식', '전동'):          '전동책상',  # 전동 = 고가
        ('소재', '원목'):               '원목',  # 그대로
        ('상판재질', '원목'):            '원목',
    }
    GENERIC_VALUES = ['있음', '없음', '가능', '불가능', '기본형', '포함', '별도구매']
    key_parts = []
    for label in PRICE_TRIGGER_LABELS:
        val = selections.get(label, '')
        if not val or val in ['상관없음', '기타']:
            continue
        # 특별 변환 먼저 체크
        special = SPECIAL_CONVERT.get((label, val))
        if special is not None:
            if special:  # 빈 문자열이면 제외
                key_parts.append(special)
        elif val in GENERIC_VALUES:
            key_parts.append(f'{label}{val}')
        else:
            key_parts.append(val)

    # 우선순위 높은 항목만 최대 2개 (구체적일수록 결과 없어서 가격 왜곡)
    PRICE_PRIORITY = [
        '높이조절방식',                             # 1순위: 높이조절 (전동이 훨씬 비쌈!)
        '인원수',                                  # 2순위: 인원수 (3인/4인/6인 가격 다름!)
        '소재', '상판재질', '가죽종류',              # 3순위: 소재
        '폭', '사이즈', '크기', '상판크기', '높이',   # 4순위: 크기
        '매트리스', '의자포함',                     # 5순위: 포함여부
        '매트리스종류',                             # 6순위: 매트리스 타입
        '형태',                                    # 7순위: 형태
    ]

    # 매트리스종류 특별 처리: 포함/별도에 따라 쿼리 다르게
    mattress_type = selections.get('매트리스종류', '')
    mattress_incl = selections.get('매트리스', '')
    if mattress_type:
        if mattress_incl == '포함':
            SPECIAL_CONVERT[('매트리스종류', mattress_type)] = f'{mattress_type}매트리스세트'
        else:
            SPECIAL_CONVERT[('매트리스종류', mattress_type)] = f'{mattress_type}매트리스'

    # 매트리스종류 선택했으면 매트리스 포함여부는 제외 (중복 방지)
    _skip_labels = set()
    if selections.get('매트리스종류'):
        _skip_labels.add('매트리스')

    priority_parts = []
    for _lbl in PRICE_PRIORITY:
        if _lbl in _skip_labels:
            continue
        _val = selections.get(_lbl, "")
        if not _val or _val in ["상관없음", "기타"]:
            continue
        _sp = SPECIAL_CONVERT.get((_lbl, _val))
        if _sp is not None:
            if _sp: priority_parts.append(_sp)
        elif _val in GENERIC_VALUES:
            priority_parts.append(f"{_lbl}{_val}")
        else:
            priority_parts.append(_val)
        if len(priority_parts) >= 3:
            break
    if not priority_parts and key_parts:
        priority_parts = key_parts[:1]

    # 조합 쿼리 생성
    combo_query = " ".join(priority_parts + [product]) if priority_parts else product
    cache_key = f'price_combo:{combo_query}'

    # 캐시 확인
    cached = _cache_get(cache_key)
    if cached:
        print(f'[가격조합캐시] {combo_query} → 캐시 히트!')
        return cached

    print(f'[가격조합] 쿼리: {combo_query}')
    result = get_price_range(combo_query)

    # 캐시 저장 (가격은 자주 안 변함 → 1시간)
    # 개발 중에 캐시 문제 있으면 60으로 줄이기
    PRICE_CACHE_TTL = 1  # 개발 중 캐시 비활성화
    if result:
        _cache_set(cache_key, result, ttl=PRICE_CACHE_TTL)

    return result


def get_price_grade(product: str) -> dict:
    """
    제품 가격 분포에서 저가/중가/고가/최고가 기준 계산
    네이버 실제 데이터 기반 (LLM 감 없음!)
    """
    cache_key = f'price_grade_v2:{product}'
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {}
    try:
        import urllib.parse as _up
        query = _up.quote(product)
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/shop?query={query}&display=100&sort=sim',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        items = data.get('items', [])

        EXCLUDE = ['렌탈', '월', '중고', '임대', '대여']
        prices = []
        for item in items:
            if item.get('productType', '1') not in ('1', ''):
                continue
            title = item.get('title', '')
            if any(e in title for e in EXCLUDE):
                continue
            lp = item.get('lprice', '0')
            try:
                p = int(lp)
                if p > 0:
                    prices.append(p)
            except:
                continue

        if len(prices) < 10:
            return {}

        prices.sort()
        trim = max(1, len(prices) * 10 // 100)
        trimmed = prices[trim:-trim] if len(prices) > trim * 2 else prices

        def fmt(p):
            return f'{round(p/50000)*5}만원'

        total = len(trimmed)
        q1 = trimmed[total // 4]
        q2 = trimmed[total // 2]
        q3 = trimmed[total * 3 // 4]

        result = {
            'min':  fmt(trimmed[0]),
            'q1':   fmt(q1),
            'q2':   fmt(q2),
            'q3':   fmt(q3),
            'max':  fmt(trimmed[-1]),
            'low':  f'{fmt(trimmed[0])} ~ {fmt(q1)}',
            'mid':  f'{fmt(q1)} ~ {fmt(q2)}',
            'high': f'{fmt(q2)} ~ {fmt(q3)}',
            'top':  f'{fmt(q3)} ~ {fmt(trimmed[-1])}',
        }
        print(f'[가격등급] {product}: 저가{result["low"]} / 중가{result["mid"]} / 고가{result["high"]}')
        _cache_set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        print(f'[가격등급오류] {e}')
        return {}


def get_price_range(product: str) -> list:
    """
    네이버 쇼핑에서 제품 가격 분포 수집
    → 실제 가격 구간 자동 생성
    캐시: 5분 유지 (같은 제품 중복 호출 방지)
    """
    cache_key = f'price_range:{product}'
    cached = _cache_get(cache_key)
    if cached:
        print(f'[가격캐시] {product} → 캐시 히트!')
        return cached

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    try:
        import urllib.parse
        query = urllib.parse.quote(product)
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/shop?query={query}&display=100&sort=sim',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        items = data.get('items', [])

        # 렌탈/중고 제외
        EXCLUDE = ['렌탈', '월', '일/', '하루', '중고', '임대', '대여']
        prices = []
        for item in items:
            # productType 필터 (일반상품만)
            if item.get('productType', '1') not in ('1', ''):
                continue
            title = item.get('title', '')
            if any(e in title for e in EXCLUDE):
                continue
            lp = item.get('lprice', '0')
            try:
                p = int(lp)
                if p > 0:
                    prices.append(p)
            except:
                continue

        if not prices:
            return []

        prices.sort()
        # 상하위 15% 극단값 제거 (초고가/초저가 이상치 방지)
        # 원목처럼 가격 편차 큰 소재도 중간값 위주로 안정적으로
        trim = max(1, len(prices) * 15 // 100)
        trimmed = prices[trim:-trim] if len(prices) > trim * 2 else prices
        mn, mx = trimmed[0], trimmed[-1]

        # 구간이 너무 좁으면 전체 범위 사용
        if mx <= mn:
            mn, mx = prices[0], prices[-1]

        # 4구간 자동 생성
        step = (mx - mn) / 4
        def fmt(p): return f"{round(p/50000)*5}만원"  # 5만원 단위 반올림
        # step이 너무 작으면 (가격 편차 없음) 최소 5만원 단위로
        if step < 50000:
            step = max(50000, (mx - mn + 200000) / 4)
        ranges = []
        seen = set()
        for i in range(4):
            lo = fmt(int(mn + step * i))
            hi = fmt(int(mn + step * (i+1)))
            label = f"{lo}~{hi}"
            if label not in seen:  # 중복 구간 제외
                ranges.append(label)
                seen.add(label)

        print(f'[가격구간] {product}: {ranges}')
        _cache_set(cache_key, ranges)
        return ranges

    except Exception as e:
        print(f'[가격구간오류] {e}')
        return []
ANTHROPIC_API_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')
NAVER_CLIENT_ID     = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
GOOGLE_API_KEY      = os.environ.get('GOOGLE_API_KEY', '')
GOOGLE_CSE_ID       = os.environ.get('GOOGLE_CSE_ID', '954e57b3b58044a16')
APIFY_TOKEN         = os.environ.get('APIFY_TOKEN', '')


# ── 백그라운드 Job 저장소 ──
_JOBS = {}  # job_id → {'status': 'pending'/'done', 'result': ...}

# ── 욕망보드 사전 수집 캐시 ──
_DESIRE_CACHE = {}  # session_id → {'status': 'pending'/'done', 'images': [...]}

def start_desire_prefetch(session_id: str, product: str, session: dict = None):
    """상황판 보여줄 때 백그라운드에서 이미지 미리 수집"""
    if session_id in _DESIRE_CACHE:
        return
    _DESIRE_CACHE[session_id] = {'status': 'pending', 'images': []}
    # 사용자 입력에서 추출한 조건 (6인용, 패브릭 등) 우선 사용
    pre_sel = (session or {}).get('_pre_selections', '')
    selections = pre_sel or (session or {}).get('selections', '')

    def run():
        try:
            images = search_desire_board_images(product, selections=selections)
            _DESIRE_CACHE[session_id] = {'status': 'done', 'images': images}
            print(f'[욕망보드 사전수집] {session_id} → {len(images)}장 완료')
        except Exception as e:
            _DESIRE_CACHE[session_id] = {'status': 'error', 'images': []}
            print(f'[욕망보드 사전수집 오류] {e}')

    threading.Thread(target=run, daemon=True).start()
    print(f'[욕망보드 사전수집] {product} 백그라운드 시작!')

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
NAVER_CLIENT_ID   = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
GOOGLE_API_KEY    = os.environ.get('GOOGLE_API_KEY', '')
GOOGLE_CSE_ID     = os.environ.get('GOOGLE_CSE_ID', '954e57b3b58044a16')


def search_google_images(keyword: str, limit: int = 3) -> list:
    """
    Google Custom Search API 이미지 검색
    하루 100건 무료
    returns: [{'url': '...', 'caption': '...'}, ...]
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print('[Google이미지] 키 없음 → 네이버로 폴백')
        return search_naver_images(keyword, limit)
    try:
        import urllib.parse
        query = urllib.parse.quote(keyword)
        url = (
            f'https://www.googleapis.com/customsearch/v1'
            f'?key={GOOGLE_API_KEY}'
            f'&cx={GOOGLE_CSE_ID}'
            f'&q={query}'
            f'&searchType=image'
            f'&num={limit}'
            f'&lr=lang_ko'
        )
        req = urllib.request.Request(url)
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read())
        items = data.get('items', [])
        images = []
        for item in items:
            url = item.get('link', '')
            caption = item.get('title', '')[:40]
            if url:
                images.append({'url': url, 'caption': caption})
        print(f'[Google이미지] {keyword} → {len(images)}개')
        return images
    except Exception as e:
        print(f'[Google이미지 오류] {e} → 네이버로 폴백')
        return search_naver_images(keyword, limit)


def search_naver_images(keyword: str, limit: int = 3) -> list:
    """
    네이버 이미지 검색 API
    returns: [{'url': '...', 'caption': '...'}, ...]
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print('[네이버이미지] 키 없음')
        return []
    try:
        import urllib.parse
        query = urllib.parse.quote(keyword)
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/image?query={query}&display={limit}&sort=sim',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        time.sleep(0.3)
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        items = data.get('items', [])
        images = []
        for item in items:
            url = item.get('link', '')
            caption = item.get('title', '').replace('<b>', '').replace('</b>', '')[:30]
            if url:
                images.append({'url': url, 'caption': caption})
        print(f'[네이버이미지] {keyword} → {len(images)}개')
        return images
    except Exception as e:
        print(f'[네이버이미지 오류] {e}')
        return []


def search_naver_shopping_images(keyword: str, limit: int = 3) -> list:
    """
    네이버 쇼핑 검색 API → 실제 제품 사진만!
    일반 이미지보다 정확도 높음
    returns: [{'url': '...', 'caption': '...'}, ...]
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print('[네이버쇼핑] 키 없음')
        return []
    try:
        import urllib.parse
        query = urllib.parse.quote(keyword)
        _offset = __import__("random").randint(1, 30)
        print(f'[오프셋] {query[:20]}... start={_offset}')
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/shop?query={query}&display={limit}&sort=sim&start={_offset}',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        time.sleep(0.3)
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        items = data.get('items', [])
        images = []
        for item in items:
            url = item.get('image', '')
            caption = item.get('title', '').replace('<b>', '').replace('</b>', '')[:30]
            link = item.get('link', '')
            price = item.get('lprice', '')
            # 제목에서 태그 자동 추출
            raw_title = item.get('title', '').replace('<b>', '').replace('</b>', '')
            TAG_KEYWORDS = ['베이지','그레이','차콜','화이트','아이보리','블랙','브라운','그린',
                           '원목','패브릭','가죽','아쿠아텍스','린넨',
                           '직선형','코너형','모듈형','카우치형',
                           '4인용','3인용','2인용','1인용','6인용',
                           '방수','커버분리','스크래치방지','발수','쿠션탈착',
                           '북유럽','모던','클래식','미니멀','럭셔리']
            tags = [t for t in TAG_KEYWORDS if t in raw_title]
            if url:
                images.append({'url': url, 'caption': caption, 'link': link, 'price': price, 'tags': tags})
        print(f'[네이버쇼핑] {keyword} → {len(images)}개')
        return images
    except Exception as e:
        print(f'[네이버쇼핑 오류] {e}')
        return []


def search_naver_shopping_with_tags(query: str, must_tags: list = [], nice_tags: list = [], limit: int = 3) -> list:
    """
    쿼리 + 태그 분리 방식:
    쿼리: 제품명 (넓게 검색)
    must_tags: 반드시 제목에 있어야 함 (AND)
    nice_tags: 하나라도 있으면 우선 (OR)
    """
    # 넓게 검색 (최대 10개)
    results = search_naver_shopping_images(query, limit=10)
    if not results:
        return []

    filtered = []
    for item in results:
        title = item.get('caption', '').lower()

        # must_tags: 전부 있어야 통과
        if must_tags and not all(tag.lower() in title for tag in must_tags):
            continue

        # nice_tags: 하나라도 있으면 점수 +1
        score = sum(1 for tag in nice_tags if tag.lower() in title)
        item['_tag_score'] = score
        filtered.append(item)

    # nice_tags 많이 포함된 순서로 정렬
    filtered.sort(key=lambda x: x.get('_tag_score', 0), reverse=True)

    print(f'[태그필터] 쿼리={query} must={must_tags} nice={nice_tags} → {len(results)}개→{len(filtered[:limit])}개')
    return filtered[:limit]


def get_color_range(product: str, material: str = None) -> list:
    """
    네이버 쇼핑에서 제품 실제 색상 수집
    → 실제 있는 색상만 반환 (없는 색상 표시 안 함)
    material: 소재 (가죽/패브릭 등) - 있으면 검색어에 포함
    캐시: 5분 유지
    """
    search_product = f'{material} {product}' if material else product
    cache_key = f'color_range:{search_product}'
    cached = _cache_get(cache_key)
    if cached:
        print(f'[컬러캐시] {product} → 캐시 히트!')
        return cached

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    try:
        import urllib.parse
        query = urllib.parse.quote(search_product)
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/shop?query={query}&display=100&sort=sim',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        items = data.get('items', [])

        # 색상 키워드 목록
        COLOR_KEYWORDS = [
            '화이트','아이보리','베이지','크림','오프화이트',
            '그레이','라이트그레이','차콜','블랙',
            '브라운','카멜','모카','카키','올리브',
            '네이비','블루','그린','민트',
            '핑크','라벤더','테라코타','버건디',
            '원목','라이트우드','미디엄우드','다크우드','우드',
        ]

        # 제목에서 색상 추출
        color_count = {}
        for item in items:
            title = item.get('title', '').replace('<b>', '').replace('</b>', '')
            for color in COLOR_KEYWORDS:
                if color in title:
                    color_count[color] = color_count.get(color, 0) + 1

        # 2개 이상 언급된 색상만 (실제로 있는 것)
        colors = [c for c, cnt in sorted(color_count.items(), key=lambda x: -x[1]) if cnt >= 2]
        colors = colors[:12]  # 최대 12개

        if not colors:
            return []

        print(f'[컬러구간] {product}: {colors}')
        _cache_set(cache_key, colors)
        return colors

    except Exception as e:
        print(f'[컬러구간오류] {e}')
        return []


# ── 제품별 힌트 규칙 ──
PRODUCT_VISION_HINTS = {
    '소파': '이것이 소파인지 확인. 의자/침대/벤치 제외. 여러 명이 앉을 수 있는 패딩된 가구여야 함.',
    '식탁': '이것이 식탁인지 확인. 커피테이블/책상/사이드테이블 제외. 식사용 테이블이어야 함.',
    '원목식탁': '상판이 나무결이 보이는 원목이어야 함. 대리석/세라믹/유리/MDF 제외.',
    '패브릭소파': '천(패브릭) 소재 소파여야 함. 가죽/인조가죽 소파 제외.',
    '가죽소파': '가죽 또는 인조가죽 소파여야 함. 패브릭/천 소파 제외.',
    '침대': '침대 프레임+매트리스 구조여야 함. 소파베드/쇼파 제외.',
    '옷장': '옷을 보관하는 장이어야 함. 책장/수납장 제외.',
}


def verify_images_batch(image_urls: list, product: str) -> list:
    """
    GPT Vision으로 여러 이미지 한번에 검증
    → API 1번 호출로 여러 장 처리
    returns: [True/False, ...] 인덱스 순서대로
    """
    if not image_urls or not OPENAI_API_KEY:
        return [True] * len(image_urls)
    try:
        hint = ''
        for key, val in PRODUCT_VISION_HINTS.items():
            if key in product:
                hint = val
                break
        if not hint:
            hint = f'이것이 {product}인지 확인.'

        # 공통 제외 조건 추가
        exclude_hint = '컬러칩, 색상표, 팬톤, 텍스트만 있는 이미지, 로고, 광고 배너, 아이콘은 NO.'

        content = []
        for i, url in enumerate(image_urls):
            content.append({
                'type': 'text',
                'text': f'이미지 {i+1}:'
            })
            content.append({
                'type': 'image_url',
                'image_url': {'url': url, 'detail': 'low'}
            })
        content.append({
            'type': 'text',
            'text': f'{hint}\n{exclude_hint}\n각 이미지가 조건에 맞으면 YES, 아니면 NO로 번호순서대로 답하세요.\n예: 1:YES 2:NO 3:YES'
        })

        body = json.dumps({
            'model': 'gpt-4o-mini',
            'max_tokens': 50,
            'messages': [{'role': 'user', 'content': content}]
        }).encode()

        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENAI_API_KEY}'
            },
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=15)
        data = json.loads(res.read())
        answer = data['choices'][0]['message']['content'].strip()
        print(f'[GPT Vision 배치] {answer}')

        results = [True] * len(image_urls)
        for part in answer.split():
            if ':' in part:
                idx_str, yn = part.split(':', 1)
                try:
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(image_urls):
                        results[idx] = 'YES' in yn.upper()
                except:
                    pass
        return results
    except Exception as e:
        print(f'[GPT Vision 배치 오류] {e}')
        return [True] * len(image_urls)
    """
    GPT Vision으로 이미지 검증
    제품에 맞는 이미지인지 YES/NO 판단
    """
    try:
        # 힌트 찾기
        hint = ''
        for key, val in PRODUCT_VISION_HINTS.items():
            if key in product:
                hint = val
                break
        if not hint:
            hint = f'이것이 {product}인지 확인.'

        body = json.dumps({
            'model': 'gpt-4o-mini',
            'max_tokens': 10,
            'messages': [{
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {'url': image_url, 'detail': 'low'}
                    },
                    {
                        'type': 'text',
                        'text': f'{hint} YES 또는 NO만 답하세요.'
                    }
                ]
            }]
        }).encode()

        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENAI_API_KEY}'
            },
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=10)
        data = json.loads(res.read())
        answer = data['choices'][0]['message']['content'].strip().upper()
        print(f'[GPT Vision] {image_url[:40]}... → {answer}')
        return 'YES' in answer
    except Exception as e:
        print(f'[GPT Vision 오류] {e}')
        return True  # 오류시 통과


def search_desire_board_images(product: str, limit_per_style: int = 1, selections: str = '') -> list:
    from main import call_llm
    """
    욕망 스토리보드 이미지 검색
    LLM으로 6가지 스타일 검색어 생성 (상황판 조건 반영!)
    returns: [{'url': '...', 'caption': '...', 'style': '...'}, ...]
    """
    # 색상 매핑 (실제 제품 태그 기반)
    COLOR_MAP = {
        '밝은톤': '베이지 아이보리 화이트',
        '중간톤': '그레이 카키 브라운',
        '어두운톤': '차콜 블랙 네이비',
    }
    FEEL_MAP = {
        '푹신함': '푹신한',
        '적당함': '약간푹신한',
        '단단함': '탄탄한',
    }
    FUNC_MAP = {
        '방수': '방수가능',
        '오염방지': '스크래치방지',
        '스크래치방지': '스크래치방지',
    }

    # 상황판 조건 파싱 → 핵심 키워드 추출
    core_keywords = []
    color_keyword = ''  # 색상 별도 관리
    _SIZE_KEYS_SET = {'인원수', '사이즈', '크기', '용량', '폭', '높이', '길이', '깊이', '상판크기'}  # 중복 방지
    if selections:
        for part in selections.split():
            if ':' in part:
                key, val = part.split(':', 1)
            else:
                key, val = '', part

            # 인원수/사이즈는 size_val로 별도 처리 → core_keywords 제외
            if key in _SIZE_KEYS_SET:
                continue
            if val in COLOR_MAP:
                color_keyword = COLOR_MAP[val].split()[0]
            elif val in FEEL_MAP:
                core_keywords.append(FEEL_MAP[val])
            elif val in FUNC_MAP:
                core_keywords.append(FUNC_MAP[val])
            elif val not in ['저가', '중가', '고가', '프리미엄', '가능', '불가능', '형태', '색상', '가격']:
                core_keywords.append(val)

    # 이율배반 조합 자동 제거!
    CONFLICT_RULES = {
        '전동': ['서랍형', '서랍', '수납서랍'],   # 전동 책상 + 서랍 불가
        '리클라이너': ['코너형', '모듈'],          # 리클라이너 + 코너형 불가
        '접이식': ['서랍형', '수납형'],             # 접이식 + 서랍 불가
    }
    for conflict_key, conflict_vals in CONFLICT_RULES.items():
        if conflict_key in core_keywords:
            before = len(core_keywords)
            core_keywords = [k for k in core_keywords if k not in conflict_vals]
            if len(core_keywords) < before:
                print(f'[이율배반 제거] {conflict_key} → {conflict_vals} 제거')

    if color_keyword:
        core_keywords.append(color_keyword)

    core_str = ' '.join(core_keywords[:4]) if core_keywords else ''

    # 인원수/사이즈 추출 (selections에서 - 항상 앞에 붙임)
    SIZE_KEYS = {'인원수', '사이즈', '크기', '용량', '폭', '높이', '길이', '깊이', '상판크기'}
    size_val = ''
    if selections:
        for part in selections.split():
            if ':' in part:
                k, v = part.split(':', 1)
                if k in SIZE_KEYS:
                    size_val = v
                    break

    # 기본 검색어: 인원수 + 핵심조건
    core_with_size = f'{size_val} {core_str}'.strip() if size_val else core_str
    base_query = f'{product} {core_with_size}'.strip()
    print(f'[욕망보드] 핵심조건: {core_with_size} / 기본검색어: {base_query}')

    try:
        # ══════════════════════════════════════════
        # [백업] 기존 LLM 쿼리 생성 방식 (v1)
        # 문제: 같은 단어 순서만 바뀌어서 다양성 없음
        # 예: '소파 4인용 원목', '4인용 원목 소파' (동일)
        # ══════════════════════════════════════════
        # style_prompt = f"""제품: "{product}"
        # 상황판 조건: "{core_str if core_str else '없음'}"
        # ... (LLM으로 6개 생성)
        # """
        # style_queries = call_llm(style_prompt, ...).strip().split('\n')
        # ══════════════════════════════════════════

        # [v2] 동현님 공식 기반 쿼리 생성
        # 공식: 기본 / 기본+컬러1 / 기본+컬러2 /
        #        기본+형태+컬러1 / 기본+기능+컬러1 / 기본+컬러1+감성
        # 장점: 같은 입력 → 같은 쿼리 (일관성)
        #        색상/기능/형태 다양하게 조합 → 이미지 다양성
        import re as _re

        # 색상 확장 (밝은톤 → 베이지, 아이보리, 화이트)
        COLOR_EXPAND = {
            '밝은톤': ['베이지', '아이보리', '화이트'],
            '중간톤': ['그레이', '카키', '브라운'],
            '어두운톤': ['차콜', '블랙', '네이비'],
        }

        # selections에서 형태/기능 추출
        형태_val = ''
        기능_val = ''
        컬러_list = []
        # 유사색 매핑 (선택 컬러 + 주변 1~2개)
        SIMILAR_COLORS = {
            '베이지':   ['베이지', '아이보리', '크림'],
            '아이보리': ['아이보리', '베이지', '크림'],
            '크림':     ['크림', '아이보리', '베이지'],
            '그레이':   ['그레이', '라이트그레이', '차콜'],
            '카키':     ['카키', '올리브', '브라운'],
            '모카':     ['모카', '브라운', '카키'],
            '차콜':     ['차콜', '블랙', '그레이'],
            '블랙':     ['블랙', '차콜', '네이비'],
            '네이비':   ['네이비', '블랙', '블루'],
            '올리브':   ['올리브', '카키', '그린'],
            '테라코타': ['테라코타', '브라운', '모카'],
            '블루':     ['블루', '네이비', '그레이'],
            '화이트':   ['화이트', '아이보리', '베이지'],
            '카멜':     ['카멜', '브라운', '베이지'],
            '브라운':   ['브라운', '카멜', '모카'],
            '버건디':   ['버건디', '브라운', '블랙'],
            '핑크':     ['핑크', '라벤더', '베이지'],
            '라벤더':   ['라벤더', '핑크', '그레이'],
            '민트':     ['민트', '블루', '그레이'],
        }
        if selections:
            for part in selections.split():
                if ':' in part:
                    k, v = part.split(':', 1)
                    if k == '형태': 형태_val = v
                    elif k in ['패브릭기능', '기능']: 기능_val = v
                    elif k == '색상' and v in COLOR_EXPAND:
                        컬러_list = COLOR_EXPAND[v]
                    elif k == '색상':
                        # 단일 색상 → 유사색으로 확장 (선택 컬러 최우선!)
                        컬러_list = SIMILAR_COLORS.get(v, [v])

        # 색상 없으면 기본 대표 색상 3개 적용
        DEFAULT_COLORS = ['베이지', '그레이', '차콜']
        if not 컬러_list:
            컬러_list = DEFAULT_COLORS
        컬러1 = 컬러_list[0]
        컬러2 = 컬러_list[1] if len(컬러_list) > 1 else ''
        컬러3 = 컬러_list[2] if len(컬러_list) > 2 else ''

        # 6가지 쿼리 공식 적용 (v2)
        # 핵심: 형태_val이 base_query에 이미 있으면 추가 안 함 (중복 방지!)
        style_queries = []
        # 1. 기본
        style_queries.append(base_query)
        # 2. 기본 + 컬러1 (선택 컬러 최우선)
        style_queries.append(f'{base_query} {컬러1}')
        # 3. 기본 + 컬러2
        style_queries.append(f'{base_query} {컬러2}' if 컬러2 else f'{base_query} {컬러1}')
        # 4. 기본 + 형태 + 컬러1 (형태가 이미 base_query에 있으면 생략)
        if 형태_val and 형태_val not in base_query:
            style_queries.append(f'{base_query} {형태_val} {컬러1}')
        else:
            style_queries.append(f'{base_query} {컬러1}')
        # 5. 기본 + 기능 + 컬러1 (기능 없으면 컬러2)
        if 기능_val and 기능_val not in base_query:
            style_queries.append(f'{base_query} {기능_val} {컬러1}')
        else:
            style_queries.append(f'{base_query} {컬러2}' if 컬러2 else f'{base_query} {컬러1}')
        # 6. 기본 + 컬러3
        style_queries.append(f'{base_query} {컬러3}' if 컬러3 else f'{base_query} {컬러1}')

        # 중복 제거
        seen = set()
        cleaned = []
        for q in style_queries:
            if q not in seen:
                seen.add(q)
                cleaned.append(q)
        style_queries = cleaned[:6]

        STYLE_NAMES = ['트렌드', '유니크', '클래식', '미니멀', '북유럽', '럭셔리']

        print(f'[욕망보드] 검색어: {style_queries}')

        # 1단계: 6개 동시 검색
        def search_one(args):
            i, query = args
            results = search_naver_shopping_images(query, limit=2)
            if not results:
                results = search_naver_images(query, limit=2)
            return i, query, results

        # 병렬 대신 순차 + 간격
        all_results = []
        for args in enumerate(style_queries):
            all_results.append(search_one(args))
            time.sleep(0.2)

        # 2단계: 각 검색어 첫번째 이미지만 모아서 배치 검증
        candidates = []
        for i, query, results in all_results:
            if results:
                candidates.append((i, query, results[0], results[1:]))

        # GPT Vision 제거 → 모든 이미지 통과 (비용 절약)
        images = []
        for i, query, results in all_results:
            if results:
                results[0]['style'] = STYLE_NAMES[i] if i < len(STYLE_NAMES) else f'스타일{i+1}'
                results[0]['query'] = query
                images.append(results[0])

        # 백업 쿼리 (size_val 포함 → 4인용 빠지지 않음)
        _base_with_size = f'{product} {size_val} {core_str}'.strip() if size_val else f'{product} {core_str}'.strip()
        backup_queries = [
            _base_with_size,
            f'{_base_with_size} 인테리어',
            f'{_base_with_size} 디자인',
            f'{product} {size_val} 인테리어'.strip(),
            f'{product} {size_val} 화이트'.strip(),
            f'{product} {size_val} 그레이'.strip(),
        ]
        existing_urls = {img['url'] for img in images}
        for bq in backup_queries:
            if len(images) >= 12:
                break
            backup = search_naver_shopping_images(bq.strip(), limit=4)
            if not backup:
                backup = search_naver_images(bq.strip(), limit=4)
            for item in backup:
                if len(images) >= 12:
                    break
                if item['url'] not in existing_urls:
                    item['style'] = '추천'
                    item['query'] = bq.strip()
                    images.append(item)
                    existing_urls.add(item['url'])

        print(f'[욕망보드] 총 {len(images)}장 수집 (6장 표시 + {max(0,len(images)-6)}장 예비)')
        return images

    except Exception as e:
        print(f'[욕망보드 오류] {e}')
        return []


def search_pexels_images(keyword: str, limit: int = 6) -> list:
    """
    Pexels API로 인테리어/라이프스타일 이미지 검색
    욕망보드용 감성 이미지 (제품 사진 아닌 공간/라이프스타일)
    """
    import os, json as _json, urllib.request, urllib.parse
    PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY', '')
    if not PEXELS_API_KEY:
        print('[Pexels] API 키 없음')
        return []
    print(f'[Pexels] API 키 확인: {PEXELS_API_KEY[:8]}...')
    try:
        encoded = urllib.parse.quote(keyword)
        url = f'https://api.pexels.com/v1/search?query={encoded}&per_page={limit}&orientation=square'
        req = urllib.request.Request(url, headers={
            'Authorization': PEXELS_API_KEY,
        })
        res = urllib.request.urlopen(req, timeout=10)
        data = _json.loads(res.read())
        images = []
        for photo in data.get('photos', []):
            images.append({
                'url': photo['src']['medium'],
                'style': keyword,
                'source': 'pexels',
                'photographer': photo.get('photographer', ''),
            })
        print(f'[Pexels] "{keyword}" → {len(images)}개')
        return images
    except Exception as e:
        print(f'[Pexels 오류] {e}')
        return []


def search_instagram_images(keyword: str, limit: int = 3) -> list:
    from main import call_llm
    """
    Apify apidojo/instagram-scraper
    startUrls 방식
    """
    if not APIFY_TOKEN:
        print('[Apify] APIFY_TOKEN 없음')
        return []
    try:
        from apify_client import ApifyClient
        client = ApifyClient(APIFY_TOKEN)
        hashtag = keyword.replace(' ', '').replace('#', '')

        # 영어로 번역 (인스타그램 해시태그용)
        try:
            translate_prompt = f'"{keyword}"를 인스타그램 해시태그용 영어로 번역하세요. 한 단어 또는 붙여쓰기로만 출력. 예: birchwood, fabricsofa'
            eng_hashtag = call_llm(translate_prompt, max_tokens=15).strip().replace(' ', '').replace('#', '')
            if eng_hashtag:
                hashtag = eng_hashtag
                print(f'[Apify] 번역: {keyword} → #{hashtag}')
        except:
            pass
        run_input = {
            "startUrls": [
                {"url": f"https://www.instagram.com/explore/tags/{hashtag}/"}
            ],
            "resultsLimit": limit,
        }
        run = client.actor("apidojo/instagram-scraper").call(run_input=run_input)
        images = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            url = item.get('displayUrl') or item.get('imageUrl') or item.get('thumbnailUrl', '')
            caption = item.get('caption', '')[:50] if item.get('caption') else ''
            if url:
                images.append({'url': url, 'caption': caption})
            if len(images) >= limit:
                break
        print(f'[Apify apidojo] {keyword} → {len(images)}개')
        return images
    except Exception as e:
        print(f'[Apify 오류] {e}')
        return []


# ===============================
# LLM 호출 (Anthropic 우선, OpenAI 폴백)
# ===============================


def search_brand_product(brand: str, product: str, limit: int = 5) -> list:
    """
    브랜드명으로 네이버 쇼핑 직접 검색
    start=1 고정 (랜덤 오프셋 없음 - 브랜드 검색 전용)
    returns: [{'name', 'price', 'image_url', 'product_url', 'mall'}, ...]
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    try:
        import urllib.parse
        query = urllib.parse.quote(f'{brand} {product}')
        req = urllib.request.Request(
            f'https://openapi.naver.com/v1/search/shop?query={query}&display={limit}&sort=sim&start=1',
            headers={
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
        )
        time.sleep(0.3)
        res = urllib.request.urlopen(req, timeout=5)
        items = json.loads(res.read()).get('items', [])
        print(f'[네이버브랜드] {brand} {product} → {len(items)}개')
        results = []
        for item in items:
            img = item.get('image', '')
            link = item.get('link', '')
            name = item.get('title', '').replace('<b>', '').replace('</b>', '')
            price = item.get('lprice', '')
            if img and link:
                results.append({
                    'name': name,
                    'price': f'{int(price):,}원' if price and price.isdigit() else '',
                    'image_url': img,
                    'product_url': link,
                    'mall': brand,
                    'brand_matched': True,
                })
        return results
    except Exception as e:
        print(f'[브랜드검색오류] {brand}: {e}')
        return []



# ===============================
# ===============================
# 바람잡이 2.0 - 동적 브랜드 추출 + 추가조건 재요청
# 범용! 소파 외 모든 카테고리 작동!
# ===============================

# 바람잡이로 처리할 추가 조건 목록 (범용!)
WIND_CONDITIONS = {
    '스툴포함': '스툴포함',
    '풀커버링': '풀커버링',
    '방수': '방수',
    '스윙': '스윙',
    '전동': '전동',
    '리클라이너': '리클라이너',
}

def search_wind_slots(raw_product: str, base_products: list, conditions: list) -> list:
    """
    바람잡이 2.0: 100개 수집된 제품에서 브랜드 추출 → 브랜드+조건 재요청!

    범용 설계:
    1단계: base_products(100개)에서 브랜드 동적 추출
    2단계: "브랜드 raw_product" → 정확한 제품명
    3단계: "브랜드 정확한제품명 조건" → 조건 포함 제품 확보!

    예:
    base_products = 100개 소파
    conditions = ['스툴포함']
    → 삼익가구, 도모, 올플로어 추출
    → "삼익가구 뉴니드 스툴포함" 확보!
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    if not base_products or not conditions:
        return []

    # 1단계: base_products에서 브랜드 동적 추출
    seen_brands = set()
    brands = []
    for p in base_products[:50]:  # 상위 50개에서 추출
        mall = p.get('mall', '').strip()
        first = p.get('name', '').split()[0] if p.get('name') else ''
        brand = mall if mall and 2 <= len(mall) <= 8 else first
        if brand and brand not in seen_brands and len(brand) >= 2:
            seen_brands.add(brand)
            brands.append(brand)
        if len(brands) >= 6:
            break

    print(f'[바람잡이2.0브랜드] {brands}')

    wind_products = []
    cond_str = ' '.join(conditions)  # "스툴포함" 또는 "스툴포함 방수"

    for brand in brands[:5]:
        # 2단계: 브랜드 + raw_product → 정확한 제품명
        step2 = search_brand_product(brand, raw_product, limit=1)
        for p in step2[:1]:
            exact_name = p.get('name', '').strip()
            if not exact_name:
                continue
            print(f'[바람잡이2.0정확명] {brand} → {exact_name[:25]}')

            # 3단계: 정확한 제품명 + 조건으로 재요청!
            step3 = search_brand_product(brand, f'{exact_name} {cond_str}', limit=2)
            for r in step3[:1]:
                r['wind_slot'] = True
                r['wind_conditions'] = conditions
                wind_products.append(r)
                print(f'[바람잡이2.0확보] {r["name"][:25]}')

    print(f'[바람잡이2.0완료] {len(wind_products)}개 확보')
    return wind_products




# 광고성 후기 필터 (블로그/카페 수집 전용)
_AD_FILTER = ['협찬', '제공받', '광고', '체험단', '모니터링', '소정의']


def search_naver_news(query: str, limit: int = 10) -> list:
    """
    네이버 뉴스 검색
    TV광고/리콜/논란 등 언론 정보 수집
    → 브랜드 추출 → 블로그 역추적으로 넘어감!
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    import urllib.parse
    enc = urllib.parse.quote(query)
    url = f'https://openapi.naver.com/v1/search/news.json?query={enc}&display={limit}&sort=sim'
    req = urllib.request.Request(url, headers={
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    })
    results = []
    try:
        res = urllib.request.urlopen(req, timeout=5)
        items = json.loads(res.read()).get('items', [])
        for item in items:
            title = re.sub(r'<[^>]+>', '', item.get('title', ''))
            desc = re.sub(r'<[^>]+>', '', item.get('description', ''))
            text = (title + ' ' + desc).strip()
            results.append({
                'text': text[:200],
                'title': title,
                'source': item.get('originallink', ''),
            })
        print(f'[뉴스검색] "{query}" → {len(results)}개')
    except Exception as e:
        print(f'[뉴스검색오류] {e}')
    return results


def _search_naver_content(product_name, content_type='blog', limit=10):
    """네이버 블로그 또는 카페 검색"""
    import urllib.parse
    results = []
    query = f'{product_name} 후기'
    enc = urllib.parse.quote(query)

    if content_type == 'blog':
        endpoint = f'https://openapi.naver.com/v1/search/blog.json?query={enc}&display={limit}&sort=sim'
        name_field = 'bloggername'
    else:
        endpoint = f'https://openapi.naver.com/v1/search/cafearticle.json?query={enc}&display={limit}&sort=sim'
        name_field = 'cafename'

    req = urllib.request.Request(endpoint, headers={
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    })
    try:
        res = urllib.request.urlopen(req, timeout=5)
        items = json.loads(res.read()).get('items', [])
        for item in items:
            link = item.get('link', '')
            desc = re.sub(r'<[^>]+>', '', item.get('description', ''))
            title = re.sub(r'<[^>]+>', '', item.get('title', ''))
            text = (title + ' ' + desc).strip()
            if any(kw in text for kw in _AD_FILTER):
                continue
            results.append({
                'text': text[:200],
                'bloggername': item.get(name_field, ''),
                'url': link,
                'source': '네이버 ' + ('블로그' if content_type == 'blog' else '카페'),
                'postdate': item.get('postdate', ''),   # ★ 날짜 (trust_layer용)
                'full_text': text[:500],                # ★ 더 긴 텍스트 (가격/감탄/부정 언어용)
            })
    except Exception as e:
        print(f'[{content_type}수집오류] {e}')
    return results


def _build_review_queries(product_name, selections=''):
    """쿼리 공식 V2 - 블로그/욕망보드 공통
    기본 + 색상 + 형태 + 기능 조합으로 다양한 쿼리 생성"""
    queries = [product_name]
    prod_words = set(product_name.split())

    if not selections:
        return queries

    색상_val = ''
    형태_val = ''
    기능_val = ''

    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '색상' and not 색상_val:
                색상_val = v
            elif k == '형태' and not 형태_val:
                형태_val = v
            elif k in ['패브릭기능', '기능'] and not 기능_val:
                기능_val = v

    if 색상_val and 색상_val not in prod_words:
        queries.append(f'{product_name} {색상_val}')
    if 형태_val and 형태_val not in prod_words:
        queries.append(f'{형태_val} {product_name}')
    if 기능_val and 기능_val not in prod_words:
        queries.append(f'{product_name} {기능_val}')

    # ★ 스툴포함 선택 시 스툴포함 쿼리 추가!
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '스툴' and v == '스툴포함':
                queries.append(f'{product_name} 스툴포함')
                break

    return queries


def _collect_blog_reviews(product_name, selections='', extra='', brand_filter=''):
    """쿼리 공식 V2로 블로그 + 카페 후기 수집 + 브랜드 필터링
    케이스2(상황판→픽코3), 케이스3(욕망보드→픽코3) 공통 적용!"""
    seen_urls = set()
    reviews_all = []

    queries = _build_review_queries(product_name, selections)
    print(f'[후기쿼리V2] {queries}')

    for query in queries:
        if len(reviews_all) >= 30:
            break
        for r in _search_naver_content(query, 'blog', limit=5):
            if r['url'] not in seen_urls:
                seen_urls.add(r['url'])
                reviews_all.append(r)
        for r in _search_naver_content(query, 'cafe', limit=5):
            if r['url'] not in seen_urls:
                seen_urls.add(r['url'])
                reviews_all.append(r)

    if brand_filter:
        before = len(reviews_all)
        reviews_all = [r for r in reviews_all if brand_filter in r['text']]
        print(f'[브랜드필터] {brand_filter} → {before}개 → {len(reviews_all)}개')

    print(f'[후기수집] {product_name} → {len(reviews_all)}개 (쿼리 {len(queries)}개)')
    return reviews_all


# ===============================
# MASTER_SCHEMA 기반 소파 상황판
# LLM 없이 코드로 빈도 분석
# 테스트: 3인용 패브릭 소파 전용
# ===============================

# 소파 마스터 스키마
# 항목명: {키워드맵: {옵션명: [매칭키워드들]}, 최소빈도: N}
SOFA_MASTER_SCHEMA = {
    '형태': {
        '키워드맵': {
            '코너형':   ['코너', 'ㄱ자', 'L자', '코너형'],
            '카우치형': ['카우치', '카우치형'],
            '모듈형':   ['모듈', '모듈형'],
            '직선형':   ['직선', '일자형', '직선형'],
        },
        '최소빈도': 2,
        '필수': False,
    },
    '기능': {
        '키워드맵': {
            '방수':     ['방수', '워터프루프', '방수기능'],
            '오염방지': ['오염방지', '오염'],
            '커버세탁': ['커버세탁', '커버분리', '세탁가능', '세탁'],
            '스윙':     ['스윙', '스윙기능'],
            '리클라이너': ['리클라이너', '리클'],
            '풀커버링': ['풀커버', '풀커버링'],
            '헤드틸팅': ['헤드틸팅', '헤드'],
        },
        '최소빈도': 2,
        '필수': False,
    },
    '스툴': {
        '키워드맵': {
            '스툴포함':   ['스툴포함', '스툴 포함', '+스툴', '스툴'],
            '스툴미포함': ['스툴미포함', '스툴 미포함'],
        },
        '최소빈도': 3,
        '필수': False,
    },
}


def build_sofa_board_from_schema(titles: list, product: str) -> str:
    """
    네이버 100개 제목 → SOFA_MASTER_SCHEMA 빈도 분석
    → LLM 없이 규칙적인 상황판 생성

    반환: 상황판 텍스트
    """
    from collections import Counter

    print(f'[스키마분석] {product} 제목 {len(titles)}개 분석 시작')

    board_lines = ['조건을 선택해주세요']

    for 항목명, 설정 in SOFA_MASTER_SCHEMA.items():
        키워드맵 = 설정['키워드맵']
        최소빈도 = 설정['최소빈도']

        # 각 옵션별 빈도 계산
        옵션_빈도 = {}
        for 옵션명, 매칭키워드들 in 키워드맵.items():
            count = sum(
                1 for title in titles
                if any(kw in title for kw in 매칭키워드들)
            )
            if count >= 최소빈도:
                옵션_빈도[옵션명] = count

        # 빈도 높은 순 정렬
        selected_opts = sorted(옵션_빈도.keys(), key=lambda x: -옵션_빈도[x])

        # 형태 항목: 직선형은 기본형이라 제목에 안 씀 → 자동 추가
        if 항목명 == '형태' and selected_opts and '직선형' not in selected_opts:
            selected_opts.append('직선형')
            print(f'[스키마] [형태] 직선형 자동 추가 (기본형)')

        if selected_opts:
            print(f'[스키마] [{항목명}] → {selected_opts} (빈도: {dict(옵션_빈도)})')
            board_lines.append(f'\n[{항목명}]')
            board_lines.append(' / '.join(selected_opts))
        else:
            print(f'[스키마] [{항목명}] → 빈도 부족, 항목 제외')

    # 색상 → get_color_range() 고정
    try:
        colors = get_color_range(product)
        if colors:
            board_lines.append('\n[색상]')
            board_lines.append(' / '.join(colors[:8]))
    except Exception as e:
        print(f'[스키마색상오류] {e}')

    # 가격 → get_price_grade() 고정
    try:
        grade = get_price_grade(product)
        if grade and grade.get('low'):
            board_lines.append('\n[가격]')
            price_opts = [
                f"저가|{grade.get('low','')}",
                f"중가|{grade.get('mid','')}",
                f"고가|{grade.get('high','')}",
                f"최고가|{grade.get('top','')}",
            ]
            board_lines.append(' / '.join(price_opts))
    except Exception as e:
        print(f'[스키마가격오류] {e}')

    # 직접입력 고정
    board_lines.append('\n[E 직접입력]')
    board_lines.append('원하는 조건을 자유롭게 입력하세요')

    result = '\n'.join(board_lines)
    print(f'[스키마완성] {product} 상황판 생성 완료')
    return result


def get_sofa_board_schema(product: str) -> str:
    """
    소파 전용 MASTER_SCHEMA 상황판
    naver_api.py get_board_pattern()의 제목 수집 재사용
    → LLM 없이 규칙적인 상황판!

    호출: board_llm.py에서 소파 감지 시 사용
    """
    cache_key = f'sofa_schema:{product}'
    cached = _cache_get(cache_key)
    if cached:
        print(f'[스키마캐시] {product} 캐시 히트!')
        return cached

    # 네이버 100개 제목 수집 (기존 로직 재사용)
    try:
        import urllib.parse as _up

        # ★ 마음 상황판으로 검색 쿼리 보강
        search_product = product
        if _MIND_CONTEXT:
            try:
                from main import call_llm
                _boost = call_llm(
                    f'제품: {product}\n사용자정보: {_MIND_CONTEXT}\n'
                    f'이 사용자에게 맞는 네이버 쇼핑 검색 키워드를 한 줄로 만들어. '
                    f'예: "캠핑 접이식 테이블", "초보자 골프 드라이버" '
                    f'키워드만 답해. 따옴표 없이.',
                    max_tokens=20
                ).strip().strip('"\'')
                if _boost and len(_boost) < 30:
                    search_product = _boost
                    print(f'[마음쿼리보강] {product} → {search_product}')
            except Exception as e:
                print(f'[마음쿼리보강오류] {e}')

        q = _up.quote(search_product)
        _headers = {
            'X-Naver-Client-Id': NAVER_CLIENT_ID,
            'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
        }
        # ★ 200개 수집 (정확도 향상)
        items = []
        for _start in [1, 101]:
            try:
                req = urllib.request.Request(
                    f'https://openapi.naver.com/v1/search/shop?query={q}&display=100&start={_start}&sort=sim',
                    headers=_headers
                )
                res = urllib.request.urlopen(req, timeout=5)
                items.extend(json.loads(res.read()).get('items', []))
            except:
                break

        # 가구/인테리어만 필터
        items = [i for i in items if '가구' in i.get('category1', '')]
        if not items:
            print(f'[스키마] 가구 카테고리 없음 → 전체 사용')
            items = json.loads(res.read()).get('items', []) if False else items

        # 제목 추출 (태그 제거)
        titles = [
            re.sub(r'<[^>]+>', '', item.get('title', ''))
            for item in items
            if item.get('title')
        ]

        print(f'[스키마] {product} → 제목 {len(titles)}개 수집')

        if len(titles) < 5:
            print(f'[스키마] 제목 부족 → None 반환')
            return ''

        result = build_sofa_board_from_schema(titles, product)

        # 10분 캐시
        _cache_set(cache_key, result, ttl=600)
        return result

    except Exception as e:
        print(f'[스키마오류] {product}: {e}')
        return ''


# ===============================
# 병렬 블로그 수집
# recommendation.py에서 분리
# naver_api.py가 API 호출 전담!
# ===============================

def collect_blog_parallel(
    blog_product: str,
    raw_product: str,
    selections: str = '',
    extra: str = '',
    brand_filter: str = '',
    board_query: str = '',
    direct_query: str = '',
) -> tuple:
    """
    블로그 3가지 수집을 병렬로 실행
    반환: (blog_reviews, board_reviews, direct_reviews)

    기본후기:   blog_product 기반 (메인)
    상황판후기: board_query 기반 (LLM 자연어 변환된 쿼리)
    직접입력:   direct_query 기반 (사용자 직접입력)
    """
    import threading

    blog_reviews    = []
    board_reviews   = []
    direct_reviews  = []

    def _collect_base():
        result = _collect_blog_reviews(
            blog_product, selections, extra, brand_filter=brand_filter
        )
        if len(result) < 5:
            result = _collect_blog_reviews(
                raw_product, selections, extra, brand_filter=brand_filter
            )
        blog_reviews.extend(result)
        print(f'[병렬-기본후기] {len(result)}개 수집완료')

    def _collect_board():
        if not board_query:
            return
        try:
            result = _search_naver_content(board_query, 'blog', limit=15)
            board_reviews.extend(result)
            print(f'[병렬-상황판후기] {len(result)}개 수집완료 (쿼리: {board_query})')
        except Exception as e:
            print(f'[병렬-상황판오류] {e}')

    def _collect_direct():
        if not direct_query:
            return
        try:
            result = _search_naver_content(direct_query, 'blog', limit=15)
            direct_reviews.extend(result)
            print(f'[병렬-직접입력후기] {len(result)}개 수집완료')
            for dr in result[:3]:
                dt = dr.get('text', '') if isinstance(dr, dict) else str(dr)
                print(f'  └ {dt[:80]}')
        except Exception as e:
            print(f'[병렬-직접입력오류] {e}')

    # 3개 동시 실행!
    t1 = threading.Thread(target=_collect_base,   daemon=True)
    t2 = threading.Thread(target=_collect_board,  daemon=True)
    t3 = threading.Thread(target=_collect_direct, daemon=True)
    t1.start(); t2.start(); t3.start()

    # timeout 5초 - 안 오면 포기!
    t1.join(timeout=5)
    if t1.is_alive():
        print('[타임아웃] 기본후기 → 단순 폴백 시도')
        try:
            blog_reviews.extend(
                _search_naver_content(raw_product.split()[-1], 'blog', limit=10)
            )
        except Exception:
            pass

    t2.join(timeout=5)
    if t2.is_alive():
        print('[타임아웃] 상황판후기 → 스킵')

    t3.join(timeout=5)
    if t3.is_alive():
        print('[타임아웃] 직접입력후기 → 스킵')

    return blog_reviews, board_reviews, direct_reviews


# ===============================
# 네이버 쇼핑 전체 검색
# recommendation.py에서 분리
# ===============================

def search_naver_shopping_full(query, limit=6, sort='', price_min=0, price_max=0, start=1, cat_id=''):
    """
    네이버 쇼핑 검색 → 제품명/이미지/가격/URL 반환
    recommendation.py에서 사용하던 _search_naver_shopping_full 이동
    """
    import urllib.parse as _up
    enc = _up.quote(query)
    sort_param   = f'&sort={sort}' if sort else ''
    price_param  = ''
    if price_min > 0:
        price_param += f'&d_price_min={price_min}'
    if price_max > 0:
        price_param += f'&d_price_max={price_max}'
    cat_param    = f'&cat_id={cat_id}' if cat_id else ''
    filter_param = '&filter=1' if not cat_id else ''
    start_param  = f'&start={start}' if start > 1 else ''
    _limit = min(limit, 100)
    url = (
        f'https://openapi.naver.com/v1/search/shop.json'
        f'?query={enc}&display={_limit}'
        f'{filter_param}{sort_param}{price_param}{cat_param}{start_param}'
    )
    if cat_id:
        print(f'[카테고리API] cat_id={cat_id} 적용')
    req = urllib.request.Request(url, headers={
        'X-Naver-Client-Id':     NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    })
    try:
        res   = urllib.request.urlopen(req, timeout=5)
        items = json.loads(res.read()).get('items', [])
        results = []
        for item in items:
            title = re.sub(r'<[^>]+>', '', item.get('title', ''))
            price = item.get('lprice', '')
            if price:
                price = f'{int(price):,}원'
            results.append({
                'name':        title,
                'price':       price,
                'image_url':   item.get('image', ''),
                'product_url': item.get('link', ''),
                'mall':        item.get('mallName', ''),
            })
        return results
    except Exception as e:
        print(f'[쇼핑검색오류] {e}')
        return []


# ===============================
# 브랜드 슬롯 1:1 수집 + 중복 추적
# ===============================

def search_brand_slots(
    brands: list,
    product_kw: str,
    limit: int = 5,
    must_conditions: dict = None,
    call_llm_fn=None,
) -> tuple:
    """
    브랜드 목록으로 1:1 네이버 쇼핑 검색
    LLM 기반 범용 검증 → 어떤 제품도 대응!
    반환: (brand_slots, seen_products)
    """
    must_conditions = must_conditions or {}
    _material = must_conditions.get('소재', '')
    _people   = must_conditions.get('인원수', '')

    # 서비스/케어 제품 제외 키워드 (소파청소, 세탁서비스 등)
    # ⚠️ '방문' 제외! 방문설치/방문배송은 제품 특성이지 서비스 아님!
    SERVICE_KEYWORDS = ['세탁', '청소', '홈케어', '서비스', '출장']

    brand_slots   = []
    seen_products = set()

    for brand in brands[:3]:
        results = search_brand_product(brand, product_kw, limit=limit)
        for r in results:
            slot_name = r.get('name', '').lower()

            # 1. 카테고리 검증 (product_kw 포함 여부)
            if product_kw and product_kw not in slot_name:
                print(f'[슬롯제외-카테고리] {r["name"][:30]}')
                continue

            # 2. 서비스 제품 제외 (소파청소업체, 세탁서비스 등)
            if any(kw in slot_name for kw in SERVICE_KEYWORDS):
                print(f'[슬롯제외-서비스] {r["name"][:30]}')
                continue

            # 3. LLM 기반 조건 검증 (소재/인원수 불일치 제외)
            if (_material or _people) and call_llm_fn:
                cond_str = ' '.join(filter(None, [_material, _people]))
                prompt = (
                    f'제품명: {r["name"][:50]}\n'
                    f'조건: {cond_str}\n\n'
                    f'제품이 조건과 맞으면 Y, 맞지 않으면 N만 출력.\n'
                    f'예: 패브릭 조건인데 가죽소파 → N\n'
                    f'예: 3인용 조건인데 4인용 → N\n'
                    f'예: 패브릭 4인용 소파 → Y'
                )
                try:
                    result = call_llm_fn(prompt, max_tokens=5).strip().upper()
                    if result.startswith('N'):
                        print(f'[슬롯제외-LLM] {r["name"][:30]}')
                        continue
                except Exception:
                    pass  # LLM 실패시 통과

            brand_slots.append(r)
            r['from_review'] = True  # ★ 리뷰 검증 출신 태깅!
            r['original'] = True     # ★ 오리지널 태깅! (200개 거치지 않음)
            seen_products.add(r['name'][:20])
            seen_products.add(r.get('product_url', ''))
            print(f'[브랜드슬롯] "{brand}" → {r["name"][:30]}')
            break

    print(f'[브랜드슬롯완료] {len(brand_slots)}개 확보 / seen={len(seen_products)}개')
    return brand_slots, seen_products



def search_pool_filtered(query: str, seen_products: set, limit: int = 200) -> list:
    """
    200개 수집 + seen_products 기반 중복 제거
    브랜드 슬롯에서 이미 본 제품 제외!
    """
    raw = search_naver_shopping_full(query, limit=100)
    raw2 = search_naver_shopping_full(query, limit=100, start=101)

    # 중복 제거 (200개 내부)
    seen_internal = set()
    merged = []
    for p in raw + raw2:
        key = p['name'][:20]
        if key not in seen_internal:
            seen_internal.add(key)
            merged.append(p)

    print(f'[풀수집] {query} → 원본 {len(raw)+len(raw2)}개 → 내부중복제거 {len(merged)}개')

    # 브랜드 슬롯 중복 제거
    filtered = []
    for p in merged:
        name_key = p['name'][:20]
        url_key = p.get('product_url', '')
        if name_key in seen_products or url_key in seen_products:
            continue
        filtered.append(p)

    print(f'[풀필터] 슬롯중복제거 후 {len(filtered)}개')
    # ★ 풀 제품은 리뷰 출신 아님 태깅!
    for p in filtered:
        p['from_review'] = False
    return filtered


# ===============================
# 더보기 캐시 필터
# recommendation.py에서 분리
# ===============================

def filter_more_pool(
    products: list,
    shown_names: set,
    shown_urls: set,
    selections: str = '',
) -> list:
    """
    더보기 캐시용 제품 필터
    1. 픽코3 카드1 노출 제품 제거
    2. 스툴 조건 불일치 제거
    3. 소재 불일치 제거 (패브릭 선택 → 가죽 제외)
    4. 인원수 불일치 제거 (4인용 선택 → 3.5인용 제외)
    """
    # 선택 조건 추출
    _stool_filters = []
    _material = ''
    _people = ''

    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k == '스툴' and v == '스툴포함':
                _stool_filters.append('스툴미포함')
            elif k == '스툴' and v == '스툴미포함':
                _stool_filters.append('스툴포함')
            elif k == '소재' and v:
                _material = v
            elif k == '인원수' and v:
                _people = v

    # 소재별 제외 키워드 (코드로 처리 - 명확한 반의어)
    MATERIAL_EXCLUDE = {
        '패브릭': ['천연가죽', '소가죽', '인조가죽', '레더', '가죽소파'],
        '가죽':   ['패브릭소파', '패브릭 소파'],
        '벨벳':   ['천연가죽', '소가죽', '인조가죽'],
    }

    # 인원수별 제외 키워드 (숫자 비교 - 코드로 처리)
    PEOPLE_EXCLUDE = {
        '2인용':   ['3인용', '3.5인용', '4인용', '5인용', '6인용'],
        '3인용':   ['2인용', '3.5인용', '4인용', '5인용', '6인용'],
        '3.5인용': ['2인용', '3인용', '4인용', '5인용', '6인용'],
        '4인용':   ['2인용', '3인용', '3.5인용', '5인용', '6인용'],
        '5인용':   ['2인용', '3인용', '3.5인용', '4인용', '6인용'],
    }

    _exclude_material = MATERIAL_EXCLUDE.get(_material, [])
    _exclude_people   = PEOPLE_EXCLUDE.get(_people, [])

    result = []
    for p in products:
        name = p.get('name', '')
        name_lower = name.lower()

        # 1. 픽코3 노출 제품 제거
        if name[:20] in shown_names:
            continue
        if p.get('product_url', '') in shown_urls:
            continue

        # 2. 스툴 조건 불일치 제거
        if any(ex in name for ex in _stool_filters):
            continue

        # 3. 소재 불일치 제거
        if any(ex in name_lower for ex in _exclude_material):
            print(f'[더보기소재제외] {name[:30]}')
            continue

        # 4. 인원수 불일치 제거
        if any(ex in name for ex in _exclude_people):
            print(f'[더보기인원제외] {name[:30]}')
            continue

        result.append(p)
    return result


# ===============================
# 더보기 캐시 저장
# recommendation.py에서 분리
# ===============================

def save_more_cache(
    cache_store: dict,
    cache_key: str,
    priced: list,
    grade_range: dict,
    shown_names: set,
    shown_urls: set,
    grade: str,
    selections: str,
    product_name: str,
    cache_ttl: float,
    lost_review_slots: list = None,  # ★ 탈락한 브랜드 슬롯
) -> None:
    """
    더보기 캐시 저장 (naver_api.py 담당!)
    픽코3 카드1 노출 제품 제외 후 저장
    """
    import time as _time
    grade_pools = {
        g: filter_more_pool(
            [p for _, p in priced[lo2:hi2]],
            shown_names, shown_urls, selections
        )
        for g, (lo2, hi2) in grade_range.items()
    }

    # ★ 탈락한 브랜드 슬롯도 더보기에 보관!
    # 가격대 안 맞아서 탈락했지만 리뷰 검증 제품 → 버리지 말자!
    if lost_review_slots:
        for p in lost_review_slots:
            p_price = 0
            try:
                p_price = int(str(p.get('price', '0')).replace(',', '').replace('원', ''))
            except:
                pass
            if p_price > 0:
                # 실제 가격 기준으로 올바른 구간에 추가
                for g, (lo2, hi2) in grade_range.items():
                    priced_prices = sorted([
                        int(str(x.get('price','0')).replace(',','').replace('원',''))
                        for _, x in priced[lo2:hi2] if x.get('price')
                    ])
                    if priced_prices:
                        g_min = priced_prices[0]
                        g_max = priced_prices[-1]
                        if g_min <= p_price <= g_max * 1.2:
                            if p not in grade_pools.get(g, []):
                                grade_pools.setdefault(g, []).insert(0, p)
                                print(f'[리뷰탈락구조] {p["name"][:20]} → {g} 더보기에 보관!')
                            break

    cache_store[cache_key] = {
        'pools':        grade_pools,
        'shown':        {grade: 0},
        'product_name': product_name,
        'selections':   selections,
        'expires':      _time.time() + cache_ttl,
    }
    print(f'[더보기캐시] {cache_key[:20]}... 저장 완료 (픽코3 {len(shown_names)}개 제외)')


# ===============================
# LLM 기반 범용 조건 매칭
# 하드코딩 COND_KEYWORDS → LLM 동적 판단
# 어떤 제품, 어떤 조건도 대응!
# ===============================

# 기준 예시 (LLM에게 참고용으로 전달)
_COND_EXAMPLES = """
헤드틸팅 → 제품명에 '헤드틸팅/틸트/틸팅' 있으면 매칭
스툴포함 → '스툴포함/스툴' 있으면 매칭
방수 → '방수/워터프루프/이지클린' 있으면 매칭
코너형 → '코너/ㄱ자/L자' 있으면 매칭
서랍형 → '서랍/2단/3단/4단' 있으면 매칭
원목 → '원목/고무나무/편백/파인' 있으면 매칭
3인용 → '3인/3인용' 있으면 매칭
퀸 → '퀸/queen' 있으면 매칭
"""

def score_products_by_conditions(
    products: list,
    check_vals: list,
    call_llm_fn=None,
) -> list:
    """
    LLM 기반 범용 조건 매칭 점수 계산
    → 하드코딩 없이 어떤 조건도 대응!
    
    반환: [(product, score), ...] 점수순 정렬
    """
    if not check_vals or not products:
        return [(p, 0) for p in products]

    # 제품명 목록 생성
    product_names = [
        f'{i+1}. {p.get("name", "")[:40]}'
        for i, p in enumerate(products)
    ]
    names_str = '\n'.join(product_names)
    conds_str = ', '.join(check_vals)

    prompt = (
        f'사용자 조건: [{conds_str}]\n\n'
        f'참고 기준 예시:\n{_COND_EXAMPLES}\n'
        f'제품 목록:\n{names_str}\n\n'
        f'각 제품이 사용자 조건과 몇 개 매칭되는지 점수로 반환해줘.\n'
        f'규칙:\n'
        f'- 기준 예시 없는 조건도 의미 파악해서 유추\n'
        f'- 소파/침대/책상/의자 등 모든 제품 적용\n'
        f'- 출력형식: 번호:점수 (예: 1:2 2:0 3:4)\n'
        f'- 숫자만, 설명 없이\n'
        f'- {len(products)}개 모두 출력'
    )

    try:
        result = call_llm_fn(prompt, max_tokens=200).strip()
        # 파싱: "1:2 2:0 3:4" → {1: 2, 2: 0, 3: 4}
        import re as _re_score
        pairs = _re_score.findall(r'(\d+):(\d+)', result)
        score_map = {int(k): int(v) for k, v in pairs}

        scored = []
        for i, p in enumerate(products):
            score = score_map.get(i + 1, 0)
            scored.append((p, score))

        # 점수 높은 순 정렬
        scored.sort(key=lambda x: -x[1])
        match_count = sum(1 for _, s in scored if s > 0)
        max_score = max(s for _, s in scored) if scored else 0
        print(f'[LLM조건매칭] 조건={check_vals} → 매칭={match_count}개 (최고점={max_score})')
        return scored

    except Exception as e:
        print(f'[LLM조건매칭오류] {e} → 폴백: 제목 텍스트 매칭')
        # 폴백: 기존 텍스트 매칭
        scored = []
        for p in products:
            name = p.get('name', '').lower()
            score = sum(2 for val in check_vals if val.lower() in name)
            scored.append((p, score))
        scored.sort(key=lambda x: -x[1])
        return scored


# ===============================
# LLM 기반 범용 검색쿼리 생성
# FORCE_SEARCH + SKIP_SEARCH 하드코딩 제거
# 어떤 제품, 어떤 조건도 대응!
# ===============================

def build_search_query(
    raw_product: str,
    selections: str,
    color_val: str = '',
    call_llm_fn=None,
) -> str:
    """
    LLM 기반 범용 검색쿼리 생성
    → FORCE_SEARCH/SKIP_SEARCH 하드코딩 불필요!

    규칙:
    - 네이버 검색에 도움되는 조건만 포함
    - 도움 안 되는 조건 제외 (일반형, 기본 등)
    - 헤드틸팅, 스툴포함 등 특수 기능은 그대로 포함
    """
    # 선택값 추출 (가격/색상 제외)
    PRIORITY_KEYS = ['인원수', '소재', '사이즈', '수납형태']
    sel_vals = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', '색상', 'E', '직접입력'] and v:
                if k in PRIORITY_KEYS:
                    sel_vals.insert(0, v)
                else:
                    sel_vals.append(v)

    if not sel_vals:
        return f'{raw_product} {color_val}'.strip() if color_val else raw_product

    sel_str = ' / '.join(sel_vals)

    if not call_llm_fn:
        # 폴백: 앞 2개 + 제품명
        return f'{" ".join(sel_vals[:2])} {raw_product}'.strip()

    prompt = (
        f'제품: {raw_product}\n'
        f'선택 옵션: {sel_str}\n'
        f'색상: {color_val or "없음"}\n\n'
        f'네이버 쇼핑 검색쿼리를 만들어줘.\n'
        f'규칙:\n'
        f'- 검색에 의미있는 조건만 포함 (일반형/기본/고정형/없음 등 제외)\n'
        f'- 특수 기능은 그대로 포함 (헤드틸팅/방수/전동 등)\n'
        f'- ★★ 스툴포함/스툴미포함 절대 금지! (검색결과 급감!)\n'
        f'- ★★ TV광고/티비광고/광고/리콜/논란 절대 금지! (검색결과 0개!)\n'
        f'- 인원수/사이즈는 반드시 포함 (3인용/퀸/킹 등)\n'
        f'- 색상이 있으면 포함\n'
        f'- ★ 직접입력/구매자맥락/직접요청 내용은 절대 포함 금지!\n'
        f'- ★ 검색쿼리는 상황판 선택 옵션만으로 구성!\n'
        f'- ★★★ 3단어 이내! 핵심 조건만! (예: "유모차 양방향", "노트북 i9")\n'
        f'- 검색쿼리 1줄만 출력'
    )
    try:
        result = call_llm_fn(prompt, max_tokens=30).strip()
        result = result.split('\n')[0].strip()
        print(f'[LLM검색쿼리] "{result}"')
        return result
    except Exception as e:
        print(f'[LLM검색쿼리오류] {e}')
        base = f'{" ".join(sel_vals[:2])} {raw_product}'.strip()
        return f'{base} {color_val}'.strip() if color_val else base


# ===============================
# 리뷰 출신 제품 우선 정렬
# recommendation.py에서 분리
# ===============================

def sort_review_first(products: list, direct_keywords: list = None) -> list:
    """
    리뷰 출신(from_review=True) 제품을 맨 앞으로!
    직접입력 키워드 매칭 제품을 리뷰끼리도 우선 정렬
    → 블로그 검증 제품 1순위 보장
    나중에 별점 기반 정렬 추가 예정
    """
    review_products = [p for p in products if p.get('from_review')]
    pool_products   = [p for p in products if not p.get('from_review')]

    # ★ 리뷰끼리도 직접입력 키워드 매칭 제품 우선!
    if direct_keywords and review_products:
        def _direct_score(p):
            name = p.get('name', '').lower()
            return sum(1 for kw in direct_keywords if kw.lower() in name)

        review_products.sort(key=_direct_score, reverse=True)
        top = review_products[0] if review_products else None
        if top:
            top_score = _direct_score(top)
            print(f'[리뷰우선] 직접입력매칭 1위: {top.get("name","")[:20]} (점수:{top_score})')

    if review_products:
        print(f'[리뷰우선] 리뷰출신 {len(review_products)}개 → 1순위 보장!')
    return review_products + pool_products


# ===============================
# 제품 4개 미만 더보기 캐시 처리
# 슬롯 제품이라도 더보기에 보관!
# ===============================

def make_small_grade_range(priced: list) -> dict:
    """
    제품 4개 미만일 때 임시 GRADE_RANGE 생성
    → 전체 제품을 모든 구간에 배치
    → 어떤 가격 버튼 눌러도 나오게!
    """
    n = len(priced)
    if n == 0:
        return {}
    # 전체를 모든 구간에 배치 (중복 허용)
    return {
        '저가':   (0, n),
        '중가':   (0, n),
        '고가':   (0, n),
        '최고가': (0, n),
    }


# ===============================
# 10개 후보 블로그 검증
# 제품명 + 직접입력으로 마음씨 확인!
# recommendation.py에서 분리
# ===============================

def verify_candidates_by_blog(
    candidates: list,
    direct_input: str,
    call_llm_fn=None,
    top_n: int = 10,
) -> tuple:
    """
    상위 N개 후보를 블로그 검증!
    제품명 + LLM변환 직접입력으로 블로그 검색
    → 후기 있으면 합격 → 픽코3 후보
    → 없으면 탈락 → 더보기 보관

    반환: (합격 목록, 탈락 목록)
    """
    if not direct_input or not candidates:
        return candidates[:top_n], []

    # ★ 핵심명사 추출 (review_builder.py 담당!)
    from review_builder import extract_direct_keywords
    _di_keywords = extract_direct_keywords(direct_input)
    _di_query = ' '.join(_di_keywords)

    print(f'[블로그검증쿼리] "{_di_query}"')

    passed = []
    failed = []

    for p in candidates[:top_n]:
        name = p.get('name', '')
        # 브랜드명 추출 (첫 단어)
        brand = name.split()[0] if name else ''
        # 검색쿼리: 브랜드 + 제품명 앞부분 + 직접입력
        search_q = f'{brand} {_di_query}'

        try:
            results = _search_naver_blog(search_q, limit=3)
            if results:
                p['direct_blog_verified'] = True
                passed.append(p)
                print(f'[블로그검증합격] {name[:25]}')
            else:
                p['direct_blog_verified'] = False
                failed.append(p)
                print(f'[블로그검증탈락] {name[:25]}')
        except:
            # 검색 실패 시 합격으로 처리 (안전)
            passed.append(p)

    print(f'[블로그검증결과] 합격={len(passed)}개 / 탈락={len(failed)}개')

    # 합격이 3개 미만이면 탈락에서 보충
    if len(passed) < 3:
        needed = 3 - len(passed)
        passed.extend(failed[:needed])
        failed = failed[needed:]

    return passed, failed


def _search_naver_blog(query: str, limit: int = 3) -> list:
    """블로그 검색 (간단 버전)"""
    import urllib.request
    import json
    _naver_id = os.environ.get('NAVER_CLIENT_ID', '')
    _naver_secret = os.environ.get('NAVER_CLIENT_SECRET', '')
    if not _naver_id:
        return []
    url = f'https://openapi.naver.com/v1/search/blog.json?query={urllib.parse.quote(query)}&display={limit}'
    req = urllib.request.Request(url)
    req.add_header('X-Naver-Client-Id', _naver_id)
    req.add_header('X-Naver-Client-Secret', _naver_secret)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('items', [])
    except:
        return []


# ============================================
# ★ 중견기업 자체몰 리뷰 수집
# 발견: 2026-05-15 동현님 & 로드
# vreview(3,800개) + 크리마(2,400개) = 6,200개!
# ============================================

# 브랜드별 리뷰 API 타입 매핑
def _mask_nickname(name: str) -> str:
    """
    구매자 닉네임 마스킹
    한글: "김민수" → "김**"
    영문: "feejin2" → "fee****"
    짧으면: "구매자"
    """
    if not name or len(name) < 2:
        return '구매자'
    import re as _re
    # 한글 이름
    if _re.search(r'[가-힣]', name):
        return name[0] + '**'
    # 영문/숫자 닉네임
    show = min(3, len(name) - 1)
    return name[:show] + '****'


BRAND_REVIEW_API = {
    # 자체 API
    '한샘': {
        'type': 'hanssem',
        'main': 'https://store.hanssem.com',
        'test_goods_no': '817730',  # 아르떼 천연가죽 소파 4인
    },

    # vreview (3,800개 쇼핑몰)
    # 1차: vreview 공식 홈페이지 자랑 고객사
    '리바트':       {'type': 'vreview', 'main': 'https://www.hyundailivart.co.kr', 'mall_id': 'e5bae7ba-09eb-467d-ba16-94497293d48e'},
    '잭슨카멜레온': {'type': 'vreview', 'main': 'https://www.jacksonchameleon.co.kr', 'mall_id': '03c44da3-f323-4545-869e-8188b0d805b5'},
    '안다르':       {'type': 'vreview', 'main': 'https://andar.co.kr'},
    '쿤달':         {'type': 'vreview', 'main': 'https://kundal.com'},
    '스탠드오일':   {'type': 'vreview', 'main': 'https://standoil.com'},
    '무무즈':       {'type': 'vreview', 'main': 'https://mumuz.co.kr'},
    '아모레퍼시픽': {'type': 'vreview', 'main': 'https://www.amoremall.com'},
    '러쉬':         {'type': 'vreview', 'main': 'https://www.lush.co.kr'},
    '몽벨':         {'type': 'vreview', 'main': 'https://www.montbell.kr'},
    '닥터그루트':   {'type': 'vreview', 'main': 'https://www.doctorgroute.com'},
    '밸롭':         {'type': 'vreview', 'main': 'https://ballop.co.kr'},
    '피지오겔':     {'type': 'vreview', 'main': 'https://www.physiogel.co.kr'},
    '블랭크':       {'type': 'vreview', 'main': 'https://www.blankcorp.co.kr'},

    # 크리마 (2,400개 쇼핑몰)
    '탑텐':     {'type': 'crema', 'domain': 'topten10mall.com'},
    '젝시믹스': {'type': 'crema', 'domain': 'xexymix.com'},
    '코오롱':   {'type': 'crema', 'domain': 'kolonmall.com'},
    '휠라':     {'type': 'crema', 'domain': 'fila.co.kr'},
    'LG전자':   {'type': 'crema', 'domain': 'lge.co.kr'},
}


def get_brand_mall_reviews(brand_name: str, product_id: str, limit: int = 100) -> list:
    """
    중견기업 자체몰 리뷰 수집
    - 한샘: gateway.hanssem.com 직접 호출
    - vreview: one.vreview.tv (리바트, 잭슨카멜레온 등)
    - 크리마: review7.cre.ma (탑텐, 젝시믹스 등) → 토큰 불필요!

    반환: [{'text': '리뷰텍스트', 'rating': 4.8, 'date': '2026-03-19', 'source': '...'}]
    """
    import requests as _req

    # 브랜드 매핑 찾기
    api_info = None
    for key, info in BRAND_REVIEW_API.items():
        if key in brand_name or brand_name in key:
            api_info = info
            break

    if not api_info:
        return []

    reviews = []

    try:
        # ── 한샘 API ──
        if api_info['type'] == 'hanssem':
            seen_texts = set()
            row_num = 0
            while len(reviews) < 100:
                url = f'https://gateway.hanssem.com/hanssem/goods-service/api/v1/goods/{product_id}/evaluations/photo-details?rowNumber={row_num}'
                r = _req.get(url, headers={
                    'Referer': 'https://store.hanssem.com/',
                    'Accept': 'application/json',
                }, timeout=8)
                if r.status_code != 200:
                    break
                data = r.json()
                items = data.get('data', [])
                if not items:
                    break
                new_count = 0
                for item in items:
                    info2 = item.get('goodsEvaluationDetailInfo', {})
                    text = info2.get('gdsEvalConts', '').strip()
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        _date = info2.get('regYmdt', '')[:10]
                        reviews.append({
                            'text': text[:300],
                            'full_text': text[:500],
                            'rating': info2.get('avgScore', ''),
                            'date': _date,
                            'postdate': _date.replace('-', ''),
                            'bloggername': '한샘몰 구매자',
                            'url': '',
                            'source': 'R1 한샘',
                        })
                        new_count += 1
                if new_count == 0:
                    break
                row_num += 3  # 3씩 증가!
            print(f'[한샘리뷰] {product_id} → {len(reviews)}개')

        # ── vreview API (리바트, 잭슨카멜레온 등) ──
        elif api_info['type'] == 'vreview':
            mall_id = api_info['mall_id']
            url = (
                f'https://one.vreview.tv/api/embed/v2/{mall_id}/reviews'
                f'?offset=0&limit={limit}&product_remote_id={product_id}&ordering=-created_at'
            )
            r = _req.get(url, headers={
                'Origin': 'https://widget2.vreview.tv',
                'Referer': 'https://widget2.vreview.tv/',
                'Accept': 'application/json',
            }, timeout=8)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('results', [])[:limit]:
                    text = item.get('text', '').strip()
                    if text:
                        _date = item.get('created_at', '')[:10]

                        # ── 닉네임 추출 + 마스킹 ──
                        _raw_nick = (
                            item.get('reviewer_name', '') or
                            item.get('author_name', '') or
                            item.get('user_name', '') or
                            item.get('nickname', '') or
                            item.get('member_name', '') or
                            (item.get('reviewer', {}) or {}).get('name', '') or
                            (item.get('author', {}) or {}).get('nickname', '') or
                            ''
                        )
                        _masked = _mask_nickname(_raw_nick) if _raw_nick else f'{brand_name} 구매자'

                        reviews.append({
                            'text': text[:300],
                            'full_text': text[:500],
                            'rating': item.get('rating', ''),
                            'date': _date,
                            'postdate': _date.replace('-', ''),
                            'bloggername': _masked,
                            'url': '',
                            'source': 'R1 브이리뷰',
                        })
            print(f'[vreview리뷰] {brand_name} {product_id} → {len(reviews)}개')

        # ── 크리마 API (탑텐, 젝시믹스 등) → 토큰 불필요! ──
        elif api_info['type'] == 'crema':
            domain = api_info['domain']
            url = (
                f'https://review7.cre.ma/api/{domain}/products/review_thumbnails'
                f'?review_id={product_id}&page=1&per={limit}'
            )
            r = _req.get(url, headers={
                'Accept': 'application/json',
                'Referer': f'https://{domain}/',
            }, timeout=8)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('reviews', [])[:limit]:
                    text = item.get('body', '') or item.get('content', '') or item.get('comment', '')
                    text = text.strip() if text else ''
                    if text:
                        _date = item.get('created_at', '')[:10]
                        reviews.append({
                            'text': text[:300],
                            'full_text': text[:500],
                            'rating': item.get('score', ''),
                            'date': _date,
                            'postdate': _date.replace('-', ''),
                            'bloggername': f'{brand_name} 구매자',
                            'url': '',
                            'source': 'R1 브이리뷰',
                        })
            print(f'[크리마리뷰] {brand_name} {product_id} → {len(reviews)}개')

    except Exception as e:
        print(f'[자체몰리뷰오류] {brand_name} {product_id}: {e}')

    return reviews


# ============================================
# ★ 업체별 패스워드(ID) 자동 추출
# 발견: 2026-05-15 동현님 & 로드
# ============================================

def auto_find_product_id(brand_name: str, product_name: str, product_url: str = '') -> str:
    """
    쇼핑몰 페이지 소스에서 product_id 자동 추출!
    vreview: HTML에서 mall_id + product_id 자동 추출
    한샘: URL에서 goods_no 추출
    크리마: HTML에서 review_id 추출
    """
    import requests as _req
    import re as _re

    api_info = None
    for key, info in BRAND_REVIEW_API.items():
        if key in brand_name or brand_name in key:
            api_info = info
            break

    if not api_info or not isinstance(api_info, dict):
        return ''

    try:
        main_url = api_info.get('main', '')
        if not main_url or not product_url:
            return ''

        # ── vreview: HTML에서 mall_id + product_id 자동 추출! ──
        if api_info['type'] == 'vreview':
            import urllib.request as _ur
            import urllib.parse as _up
            import os as _os

            # 1. 네이버 쇼핑에서 공식몰 URL 찾기!
            main_domain = main_url.replace('https://', '').replace('http://', '').split('/')[0]
            encoded_q = _up.quote(product_name)
            naver_url = f'https://openapi.naver.com/v1/search/shop.json?query={encoded_q}&display=20&sort=sim'
            naver_req = _ur.Request(naver_url)
            naver_req.add_header('X-Naver-Client-Id', _os.environ.get('NAVER_CLIENT_ID', ''))
            naver_req.add_header('X-Naver-Client-Secret', _os.environ.get('NAVER_CLIENT_SECRET', ''))

            official_url = ''
            try:
                with _ur.urlopen(naver_req, timeout=8) as resp:
                    ndata = __import__('json').loads(resp.read().decode('utf-8'))
                for item in ndata.get('items', []):
                    link = item.get('link', '')
                    if main_domain in link or main_url.replace('https://www.', '').split('/')[0] in link:
                        official_url = link
                        break
            except Exception as _e:
                print(f'[패스워드] 네이버 검색 오류: {_e}')

            if not official_url:
                print(f'[패스워드실패] {brand_name} → 공식몰 URL 못찾음')
                return ''

            # 2. product_id: 공식몰 URL에서 추출!
            _pid = ''
            for pattern in [r'/p/(P\d+)', r'product_no=(\d+)', r'goodsNo=(\d+)']:
                m = _re.search(pattern, official_url)
                if m:
                    _pid = m.group(1)
                    break

            if not _pid:
                print(f'[패스워드실패] {brand_name} → product_id 추출 못함')
                return ''

            # 3. mall_id: 공식몰 제품 페이지 HTML에서 vrid= 추출!
            r = _req.get(official_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }, timeout=10)
            html = r.text

            m = _re.search(r'vrid=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', html)
            if m:
                _mall_id = m.group(1)
                api_info['mall_id'] = _mall_id  # 자동 업데이트!
                print(f'[패스워드] {brand_name} mall_id={_mall_id} product_id={_pid}')
                return _pid
            else:
                print(f'[패스워드실패] {brand_name} → mall_id 추출 못함')
                return ''

        # ── 한샘: URL에서 goods_no 추출 ──
        elif api_info['type'] == 'hanssem':
            for pattern in [r'/goods/(\d+)', r'goodsNo=(\d+)', r'PRODUCTNO=(\d+)']:
                m = _re.search(pattern, product_url)
                if m:
                    print(f'[패스워드] 한샘 goods_no={m.group(1)}')
                    return m.group(1)

        # ── 크리마: HTML에서 review_id 추출 ──
        elif api_info['type'] == 'crema':
            if product_url:
                r = _req.get(product_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                html = r.text
                for pattern in [r'review_id=(\d+)', r'widget_id=(\d+)']:
                    m = _re.search(pattern, html)
                    if m:
                        print(f'[패스워드] 크리마 review_id={m.group(1)}')
                        return m.group(1)

    except Exception as e:
        print(f'[패스워드오류] {brand_name}: {e}')

    print(f'[패스워드실패] {brand_name} → 추출 못함')
    return ''


# ============================================
# ★ 공식몰 URL 자동 탐색 + 리뷰 시스템 자동 감지
# 동현님 설계 / 로드 구현 2026-05-16
# ============================================

def find_official_url(naver_items: list, brand_name: str = '') -> dict:
    """
    네이버 쇼핑 결과에서 리뷰가 많은 쪽 URL 선택

    핵심 원칙: URL 우선순위 아님 → 리뷰 수 우선순위!
    사용자는 리뷰 많은 곳에서 구매 → 거기가 진짜 판매처

    반환:
    {
        'url': 선택된 URL,
        'tier': '공식몰' / 'brand.naver' / 'smartstore' / '종합몰',
        'review_count': 리뷰 수,
        'official_url': 공식몰 URL (리뷰 합산용),
    }
    """
    import re as _re

    # BRAND_REVIEW_API에서 공식 도메인 힌트
    official_domains = []
    if brand_name:
        for key, info in BRAND_REVIEW_API.items():
            if key in brand_name or brand_name in key:
                main = info.get('main', '')
                if main:
                    d = main.replace('https://www.', '').replace('https://', '').split('/')[0]
                    official_domains.append(d)

    # 각 URL별 리뷰 수 수집
    candidates = []
    for item in naver_items:
        link         = item.get('link', '')
        mall         = item.get('mallName', '')
        review_count = int(item.get('reviewCount', 0) or 0)
        if not link:
            continue

        # 타입 분류
        if official_domains and any(d in link for d in official_domains):
            tier = '공식몰'
        elif 'brand.naver.com' in link:
            tier = 'brand.naver'
        elif 'smartstore.naver.com' in link and 'smartstore.naver.com/main' not in link:
            tier = 'smartstore'
        elif any(s in link for s in ['coupang.com', 'ssg.com', 'lotte.com', 'gmarket.co.kr']):
            tier = '종합몰'
        else:
            tier = '기타'

        candidates.append({
            'url': link,
            'tier': tier,
            'mall': mall,
            'review_count': review_count,
        })

    if not candidates:
        return {'url': '', 'tier': '', 'review_count': 0, 'official_url': ''}

    # ── 핵심: 리뷰 수 기준으로 정렬 ──
    # 단, 종합몰/기타는 마지막 (픽코가 직접 연결 안 하는 게 나음)
    TIER_WEIGHT = {'공식몰': 0, 'brand.naver': 1, 'smartstore': 2, '종합몰': 3, '기타': 4}
    candidates.sort(key=lambda x: (TIER_WEIGHT.get(x['tier'], 4), -x['review_count']))

    # 리뷰 수 비교: 공식몰 vs 스마트스토어
    official = next((c for c in candidates if c['tier'] == '공식몰'), None)
    smart    = next((c for c in candidates if c['tier'] in ['brand.naver', 'smartstore']), None)

    if official and smart:
        # 리뷰 수 많은 쪽 선택
        if smart['review_count'] > official['review_count'] * 2:
            # 스마트스토어 리뷰가 2배 이상 많으면 → 스마트스토어
            winner = smart
            print(f'[URL선택] {brand_name} 스마트스토어 승리 (리뷰 {smart["review_count"]} vs 공식몰 {official["review_count"]})')
        else:
            # 공식몰 우선 (리뷰 합산 가능 + vreview 접근)
            winner = official
            print(f'[URL선택] {brand_name} 공식몰 선택 (리뷰 {official["review_count"]} vs 스마트 {smart["review_count"]})')
    else:
        winner = candidates[0]
        print(f'[URL선택] {brand_name} {winner["tier"]} (리뷰 {winner["review_count"]})')

    return {
        'url':          winner['url'],
        'tier':         winner['tier'],
        'review_count': winner['review_count'],
        'official_url': official['url'] if official else '',  # 리뷰 합산용
    }


def auto_detect_and_fetch_reviews(product_url: str, product_name: str = '', limit: int = 10) -> list:
    """
    어떤 제품 URL이든 → 리뷰 시스템 자동 감지 → 리뷰 가져오기

    BRAND_REVIEW_API에 없는 브랜드도 자동 처리!

    감지 순서:
    1. vreview.tv → vreview API
    2. cre.ma     → 크리마 API
    3. hanssem    → 한샘 API
    4. 없으면 []  → 블로그 리뷰로 폴백
    """
    import requests as _req
    import re as _re

    if not product_url:
        return []

    reviews = []

    try:
        r = _req.get(product_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }, timeout=10, allow_redirects=True)
        html      = r.text
        final_url = r.url
        base_url  = f'https://{final_url.split("/")[2]}'

        # ── vreview 감지 ──
        if 'vreview.tv' in html:
            # mall_id 추출
            m_mall = _re.search(
                r'vrid[=\s"\':()+]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                html, _re.IGNORECASE
            )
            mall_id = m_mall.group(1) if m_mall else ''

            # product_id 추출
            pid_patterns = [
                r'product[_\-]?(?:remote[_\-]?)?id["\s:=\'(]+([A-Z]?\d{4,})',
                r'"product_no"\s*:\s*(\d{4,})',
                r'data-product[_\-]?id=["\']([A-Z]?\d{4,})',
                r'/goods/(\d{4,})',
                r'/products?/(\d{4,})',
                r'product_no=(\d{4,})',
                r'/p/(P\d+)',
            ]
            product_id = ''
            search_text = final_url + html[:6000]
            for pat in pid_patterns:
                pm = _re.search(pat, search_text, _re.IGNORECASE)
                if pm:
                    product_id = pm.group(1)
                    break

            if mall_id and product_id:
                rv = _req.get(
                    f'https://one.vreview.tv/api/embed/v2/{mall_id}/reviews',
                    params={'offset': 0, 'limit': limit, 'product_remote_id': product_id, 'ordering': '-created_at'},
                    headers={'Origin': base_url, 'Referer': final_url, 'Accept': 'application/json'},
                    timeout=8
                )
                if rv.status_code == 200:
                    data = rv.json()
                    for item in data.get('results', [])[:limit]:
                        text = item.get('text', '').strip()
                        if text:
                            _date = item.get('created_at', '')[:10]
                            reviews.append({
                                'text': text[:300],
                                'full_text': text[:500],
                                'rating': item.get('rating', ''),
                                'date': _date,
                                'postdate': _date.replace('-', ''),
                                'bloggername': '구매자',
                                'url': product_url,
                                'source': 'R1 브이리뷰',  # ★ R1 표시
                            })
                print(f'[자동감지] vreview → mall_id={mall_id[:8]} product_id={product_id} → {len(reviews)}개')
                return reviews

        # ── 크리마 감지 ──
        if 'cre.ma' in html or 'crema' in html.lower():
            m_domain = _re.search(r'review\d*\.cre\.ma/[^/]+/([\w\.\-]+)/', html)
            domain   = m_domain.group(1) if m_domain else _re.search(r'https?://([\w\.\-]+)/', final_url).group(1)

            pid_m = _re.search(r'review_id=(\d+)|widget_id=(\d+)|product_no=(\d+)', html)
            product_id = (pid_m.group(1) or pid_m.group(2) or pid_m.group(3)) if pid_m else ''

            if domain and product_id:
                rc = _req.get(
                    f'https://review7.cre.ma/api/{domain}/products/review_thumbnails',
                    params={'review_id': product_id, 'page': 1, 'per': limit},
                    headers={'Accept': 'application/json', 'Referer': base_url + '/'},
                    timeout=8
                )
                if rc.status_code == 200:
                    data = rc.json()
                    for item in data.get('reviews', [])[:limit]:
                        text = (item.get('body') or item.get('content') or item.get('comment') or '').strip()
                        if text:
                            _date = item.get('created_at', '')[:10]
                            reviews.append({
                                'text': text[:300],
                                'full_text': text[:500],
                                'rating': item.get('score', ''),
                                'date': _date,
                                'postdate': _date.replace('-', ''),
                                'bloggername': '구매자',
                                'url': product_url,
                                'source': 'R2 크리마',  # ★ R2 표시
                            })
                print(f'[자동감지] 크리마 → domain={domain} product_id={product_id} → {len(reviews)}개')
                return reviews

        # ── 한샘 감지 ──
        if 'hanssem' in html.lower() or 'hanssem' in final_url:
            pid_m = _re.search(r'/goods/(\d+)|goodsNo=(\d+)', final_url + html[:2000])
            product_id = (pid_m.group(1) or pid_m.group(2)) if pid_m else ''
            if product_id:
                reviews = get_brand_mall_reviews('한샘', product_id, limit)
                for rv in reviews:
                    rv['source'] = 'R1 한샘'
                print(f'[자동감지] 한샘 → product_id={product_id} → {len(reviews)}개')
                return reviews

        print(f'[자동감지] 리뷰 시스템 없음 → 블로그로 폴백: {product_url[:60]}')

    except Exception as e:
        print(f'[자동감지오류] {product_url[:60]}: {e}')

    return []


def get_product_features_from_blog(product_name: str, call_llm_fn=None) -> list:
    """
    제품명에서 핵심 특징 추출
    1. 키워드 매칭 (즉시)
    2. LLM 보완 (키워드 부족할 때)
    """
    if not product_name:
        return []

    try:
        FEATURE_KEYWORDS = {
            '아쿠아텍스': '아쿠아텍스 생활방수 소재',
            '헤드틸팅': '헤드틸팅 각도 조절',
            '무빙헤드': '무빙헤드 각도 조절',
            '스윙': '스윙 등받이 기능',
            '리클라이너': '리클라이너 각도 조절',
            '풀커버링': '풀커버 탈부착 가능',
            '모듈형': '모듈형 자유 배치',
            '코너형': 'ㄱ자 코너형 구조',
            '카우치형': '카우치 눕기 가능',
            '전동': '전동 리클라이닝',
            '구스': '구스 다운 쿠션',
            '원목': '원목 프레임',
            '이지클린': '이지클린 세탁 가능',
            '방수': '생활방수 처리',
            '소가죽': '천연 소가죽 소재',
            '벨벳': '벨벳 원단',
            '스툴포함': '스툴 포함 구성',
            '직선형': '직선형 심플 디자인',
            '패브릭': '패브릭 소재',
            '가죽': '가죽 소재',
        }

        features = []
        for kw, desc in FEATURE_KEYWORDS.items():
            if kw in product_name and desc not in features:
                features.append(desc)
                if len(features) >= 4:
                    break

        # LLM 보완 (키워드 부족 or call_llm 있을 때)
        if call_llm_fn:
            need = 3 - len(features)
            if need > 0:
                prompt = f"""소파 제품명: {product_name}

이 제품의 핵심 특징 {need}가지를 뽑아주세요.
이미 뽑힌 특징: {", ".join(features) if features else "없음"}
규칙: 한 줄에 하나, 15자 이내, 소재/기능/구조만, 번호 없이"""
                try:
                    result = call_llm_fn(prompt, max_tokens=100).strip()
                    for line in result.split('\n'):
                        line = line.strip()
                        if line and len(line) >= 4 and line not in features and len(features) < 5:
                            features.append(line)
                except:
                    pass

        print(f'[제품특징] {product_name[:20]} → {len(features)}개: {features}')
        return features[:5]

    except Exception as e:
        print(f'[제품특징오류] {e}')
        return []
