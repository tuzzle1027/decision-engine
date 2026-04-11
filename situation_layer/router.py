# Picko Router - 분리기 v2
# 핵심 원칙: 끝까지 다 읽고 한번에 결정!

import json
import os
import re

def _load_brands():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, '..', 'brands.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        result = {}
        for b in data['brands']:
            result[b['brand']] = {'category': b['category'], 'country': b['country']}
        return result
    except Exception as e:
        print(f'[브랜드 로드 오류] {e}')
        return {}

BRANDS = _load_brands()

TREND_KEYWORDS = [
    '베스트셀러', '인기', '핫한', '요즘', '신상',
    '평점높은', '많이팔리는',
    '랭킹', '순위', '트렌드', '화제', '요즘뜨는'
]

SOLUTION_KEYWORDS = {
    '러닝':    ['러닝화', '스마트워치', '러닝복', '이어폰'],
    '등산':    ['등산화', '배낭', '등산스틱', '등산복', '헤드랜턴'],
    '캠핑':    ['텐트', '침낭', '버너', '랜턴', '캠핑의자'],
    '낚시':    ['낚싯대', '릴', '루어', '낚시조끼'],
    '서핑':    ['서프보드', '웻슈트', '서핑왁스', '리쉬'],
    '자전거':  ['자전거', '헬멧', '자전거장갑', '라이트'],
    '헬스':    ['헬스장가방', '운동복', '프로틴', '운동화', '스마트워치'],
    '다이어트':['운동용품', '식단용품', '체중계', '운동복'],
    '요가':    ['요가매트', '요가블록', '요가복'],
    '스키':    ['스키', '스키부츠', '폴', '고글', '스키복'],
}

SOLUTION_TRIGGERS = [
    '시작하려고', '입문하려고', '장비 추천', '뭐가 필요',
    '준비하려고', '해보려고', '처음인데', '초보인데'
]

SOLUTION_COPIES = {
    '러닝':    '첫 발걸음이 천 리를 만들어요! 🏃',
    '등산':    '산이 당신을 기다리고 있어요! ⛰️',
    '캠핑':    '별빛 아래 당신만의 집! 🏕️',
    '낚시':    '기다림이 주는 최고의 선물! 🎣',
    '서핑':    '파도가 당신을 부르고 있어요! 🏄',
    '자전거':  '바람이 되는 그 순간! 🚴',
    '헬스':    '오늘이 바로 그 날이에요! 💪',
    '다이어트':'당신이 선택한 오늘이 가장 빛나는 날! ✨',
    '요가':    '몸과 마음이 하나되는 시간! 🧘',
    '스키':    '설원 위에서 자유를 느껴요! ⛷️',
}

LARGE_CATEGORY = {
    '신발':     ['운동화', '구두', '부츠', '샌들', '슬리퍼'],
    '옷':       ['상의', '하의', '아우터', '속옷', '원피스'],
    '화장품':   ['스킨케어', '메이크업', '헤어', '바디'],
    '식품':     ['고기', '채소', '과일', '가공식품', '음료'],
    '취미용품': ['게임', '운동', '독서', '음악', '미술'],
    '전자제품': ['노트북', '스마트폰', '태블릿', '카메라', '오디오'],
}

DIRECT_PRODUCTS = {
    '노트북', '맥북', '맥북에어', '맥북프로',
    '냉장고', '김치냉장고', '양문형냉장고',
    '소파', '쇼파', '소파베드', '소파침대', '소파 침대',
    '운동화', '러닝화', '트레이닝화', '축구화', '농구화',
    '청소기', '로봇청소기', '무선청소기', '스팀청소기',
    '헤드폰', '이어폰', '에어팟', '헤드셋',
    '수영복', '래쉬가드', '비키니', '원피스수영복',
    '책', '도서', '소설', '팝업북', '그림책', '동화책',
    '캠핑', '텐트', '침낭', '버너',
    '자전거', '킥보드',
    # 가구/인테리어
    '침대', '슈퍼싱글', '싱글침대', '퀸침대', '킹침대', '매트리스', '책상', '의자', '식탁',
    '옷장', '서랍장', '책장', '화장대', '신발장',
    '수납가구', '거실장', 'TV장',
    '커튼', '블라인드', '러그', '카페트',
    '액자', '거울', '화분', '캔들', '디퓨저', '쿠션', '조명',
    '원목식탁', '대리석식탁', '세라믹식탁',
    '학생책상', '사무책상', '게이밍책상',
    '암막커튼', '린넨커튼', '쉬폰커튼',
    '인테리어소품', '탁상시계', '벽시계',
}

CONTEXT_MAP = {
    '가정':  ['가정', '집', '가정용', '가족'],
    '사무실':['사무실', '회사', '사무용', '오피스'],
    '업소':  ['업소', '식당', '카페', '상업용'],
    '남성':  ['남성', '남자', '남자용', '남', '남편', '아빠', '아버지'],
    '여성':  ['여성', '여자', '여자용', '여', '아내', '엄마', '어머니'],
    '아동':  ['아동', '아이', '어린이', '키즈', '유아', '아기',
              '베이비', '영아', '갓난', '돌쟁이', '신생아', '유아기'],
    '원목':     ['원목'],
    '대리석':   ['대리석'],
    '세라믹':   ['세라믹'],
    '학생용':   ['학생', '학생용'],
    '사무용':   ['사무용', '업무용'],
    '게이밍':   ['게이밍', '게임용'],
    '암막커튼': ['암막'],
    '인테리어소품': ['인테리어소품', '인테리어 소품'],
    '패브릭': ['패브릭', '천소파'],
    '가죽':   ['가죽소파', '가죽'],
    '슈퍼싱글': ['슈퍼싱글'],
    '퀸':      ['퀸'],
    '킹':      ['킹'],
    '싱글':    ['싱글침대', '싱글 침대'],
}

BRAND_WIDE_CATEGORIES = [
    '주방용품', '청소용품', '욕실용품', '생활용품', '문구',
    '가구', '거실가구', '침실가구', '주방가구',
    '전자제품', '가전', '의류', '신발', '식품',
]

FURNITURE_KEYWORDS = [
    '가구', '거실가구', '침실가구', '주방가구', '인테리어가구',
    '거실 인테리어', '방 인테리어', '집 인테리어', '홈인테리어',
    '인테리어 바꾸', '인테리어 하고', '인테리어 꾸미',
    '집 꾸미', '방 꾸미', '거실 꾸미',
    '신혼집 꾸밀', '이사하는데 가구', '이사 가구',
]
FURNITURE_CATEGORY_ITEMS = [
    '침대', '매트리스', '소파', '책상', '의자',
    '식탁', '수납가구', '커튼', '러그', '인테리어소품'
]

# ── 감지 함수들 ──
def _detect_trend(q):
    for kw in TREND_KEYWORDS:
        if kw in q:
            return kw
    return ''

def _detect_solution(q):
    for activity in SOLUTION_KEYWORDS:
        if activity in q:
            for trigger in SOLUTION_TRIGGERS:
                if trigger in q:
                    return activity
    return ''

def _detect_brand(q):
    for brand in BRANDS:
        if brand in q:
            return brand
    return ''

def _detect_large_category(q):
    for large, subs in LARGE_CATEGORY.items():
        if large in q:
            return (large, subs)
    return ('', [])

def _detect_product(q):
    sorted_products = sorted(DIRECT_PRODUCTS, key=len, reverse=True)
    for prod in sorted_products:
        if prod in q:
            return prod
    return ''

def _detect_context(q):
    for context, keywords in CONTEXT_MAP.items():
        for kw in keywords:
            if kw in q:
                return context
    return ''

def _detect_brand_category(q, brand):
    if not brand:
        return ''
    for cat in BRAND_WIDE_CATEGORIES:
        if cat in q:
            return cat
    return ''

def _detect_furniture_category(q, product, brand):
    """가구 대분류 감지 (개별 제품 없을 때만)"""
    INTERIOR_PATTERNS = ['인테리어 바꾸', '인테리어 하고', '인테리어 꾸미',
                         '집 꾸미', '방 꾸미', '거실 꾸미']
    # 인테리어 패턴이면 제품 있어도 통과
    is_interior_pattern = any(p in q for p in INTERIOR_PATTERNS)
    if product and not is_interior_pattern:
        return False
    for kw in FURNITURE_KEYWORDS:
        if kw in q:
            return True
    if brand:
        for cat in ['가구', '거실가구', '침실가구']:
            if cat in q:
                return True
    return False

# ── 메인 라우터 ──
def route(query: str, selected: dict = None) -> dict:
    q = query.strip()
    selected = selected or {}

    trend        = _detect_trend(q)
    solution     = _detect_solution(q)
    brand        = _detect_brand(q)
    large, subs  = _detect_large_category(q)
    product      = _detect_product(q)
    context      = _detect_context(q)
    brand_cat    = _detect_brand_category(q, brand)
    is_furniture = _detect_furniture_category(q, product, brand)

    result = {
        'zone':    '3',
        'mode':    'board',
        'product': product or q,
        'brand':   brand,
        'context': context,
        'solution':'',
        'message': '',
        'items':   [],
    }

    if trend:
        result.update({'zone':'direct', 'mode':'trend', 'product':q})
        return result

    if solution:
        result.update({
            'zone':'solution', 'mode':'solution',
            'solution':solution,
            'message':SOLUTION_COPIES.get(solution,'함께 준비해요! 😊'),
            'items':SOLUTION_KEYWORDS.get(solution,[])
        })
        return result

    if brand and not product and not large and not brand_cat:
        from price_config import BRAND_GREETINGS
        result.update({
            'zone':'0', 'mode':'brand_ask',
            'message':BRAND_GREETINGS.get(brand, BRAND_GREETINGS['default'])
        })
        return result

    if brand and brand_cat:
        result.update({'zone':'2', 'mode':'brand_category', 'product':brand_cat})
        return result

    if is_furniture:
        result.update({
            'zone': 'furniture_category',
            'mode': 'furniture_category',
            'product': '가구',
            'items': FURNITURE_CATEGORY_ITEMS,
            'brand': brand,
        })
        return result

    if large and not product:
        result.update({'zone':'2', 'mode':'large_category', 'product':large, 'items':subs})
        return result

    if product:
        try:
            from situation_layer.boards.board_furniture import get_zone, ZONE_RULES, FURNITURE_2ZONE
            rule = ZONE_RULES.get(product, {})
            merged = dict(selected)
            # context가 실제 2구역 옵션값인 경우만 merged에 포함
            if context and rule.get('context_key'):
                valid_options = FURNITURE_2ZONE.get(product, [])
                if context in valid_options:
                    merged[rule['context_key']] = context
            actual_zone = get_zone(product, merged)
        except Exception as e:
            print(f'[zone 판단 오류] {e}')
            actual_zone = '3'
        result.update({'zone': actual_zone, 'mode':'board', 'product':product, 'context':context})
        return result

    result['product'] = q
    return result


if __name__ == '__main__':
    tests = [
        '가구 찾아줘',
        '이케아 가구 찾아줘',
        '한샘 가구 찾아줘',
        '소파 찾아줘',
        '침대 찾아줘',
    ]
    print('=' * 50)
    for q in tests:
        r = route(q)
        print(f'입력: {q}')
        print(f'  zone:{r["zone"]} product:{r["product"]} items:{r["items"]}')
        print()
