# Picko Router - 분리기
# 사용자 입력 → 어느 구역/상황판으로 보낼지 결정
#
# 규칙:
# 1. 브랜드만 입력 → 0구역 (되물음)
# 2. 브랜드 + 카테고리 → 2구역
# 3. 브랜드 + 제품명 명확 → 3구역 직행
# 4. 대분류 → 2구역 2단계
# 5. 중분류 → 2구역 1단계
# 6. 소분류/명확 → 3구역 직행
# 7. 트렌드 키워드 → Direct Mode (검색 직행)
# 8. 취미/활동 키워드 → Solution Mode

import json
import os
import re

# ─────────────────────────────────────────
# 브랜드 로드
# ─────────────────────────────────────────
def _load_brands():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, '..', 'brands.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        result = {}
        for b in data['brands']:
            result[b['brand']] = {
                'category': b['category'],
                'country': b['country']
            }
        return result
    except Exception as e:
        print(f'[브랜드 로드 오류] {e}')
        return {}

BRANDS = _load_brands()

# ─────────────────────────────────────────
# 트렌드 키워드 → 검색 직행
# ─────────────────────────────────────────
TREND_KEYWORDS = [
    '베스트셀러', '인기', '핫한', '요즘', '신상',
    '가성비', '평점높은', '많이팔리는',
    '랭킹', '순위', '트렌드', '화제', '요즘뜨는'
]

# ─────────────────────────────────────────
# Solution Mode 키워드 (취미/활동)
# ─────────────────────────────────────────
SOLUTION_KEYWORDS = {
    '러닝': ['러닝화', '스마트워치', '러닝복', '이어폰'],
    '등산': ['등산화', '배낭', '등산스틱', '등산복', '헤드랜턴'],
    '캠핑': ['텐트', '침낭', '버너', '랜턴', '캠핑의자'],
    '낚시': ['낚싯대', '릴', '루어', '낚시조끼'],
    '서핑': ['서프보드', '웻슈트', '서핑왁스', '리쉬'],
    '자전거': ['자전거', '헬멧', '자전거장갑', '라이트'],
    '헬스': ['헬스장가방', '운동복', '프로틴', '운동화', '스마트워치'],
    '다이어트': ['운동용품', '식단용품', '체중계', '운동복'],
    '요가': ['요가매트', '요가블록', '요가복'],
    '스키': ['스키', '스키부츠', '폴', '고글', '스키복'],
}

# Solution Mode 감지 키워드
SOLUTION_TRIGGERS = [
    '시작하려고', '입문하려고', '장비 추천', '뭐가 필요',
    '준비하려고', '해보려고', '처음인데', '초보인데'
]

# Solution Mode 감동 카피
SOLUTION_COPIES = {
    '러닝': '첫 발걸음이 천 리를 만들어요! 🏃',
    '등산': '산이 당신을 기다리고 있어요! ⛰️',
    '캠핑': '별빛 아래 당신만의 집! 🏕️',
    '낚시': '기다림이 주는 최고의 선물! 🎣',
    '서핑': '파도가 당신을 부르고 있어요! 🏄',
    '자전거': '바람이 되는 그 순간! 🚴',
    '헬스': '오늘이 바로 그 날이에요! 💪',
    '다이어트': '당신이 선택한 오늘이 가장 빛나는 날! ✨',
    '요가': '몸과 마음이 하나되는 시간! 🧘',
    '스키': '설원 위에서 자유를 느껴요! ⛷️',
}

# ─────────────────────────────────────────
# 대분류 → 2구역 2단계
# ─────────────────────────────────────────
LARGE_CATEGORY = {
    '신발': ['운동화', '구두', '부츠', '샌들', '슬리퍼'],
    '옷': ['상의', '하의', '아우터', '속옷', '원피스'],
    '화장품': ['스킨케어', '메이크업', '헤어', '바디'],
    '가구': ['소파', '침대', '책상', '수납', '조명'],
    '식품': ['고기', '채소', '과일', '가공식품', '음료'],
    '취미용품': ['게임', '운동', '독서', '음악', '미술'],
    '전자제품': ['노트북', '스마트폰', '태블릿', '카메라', '오디오'],
}

# ─────────────────────────────────────────
# 제품명 → 3구역 직행 (소분류/명확)
# ─────────────────────────────────────────
DIRECT_PRODUCTS = {
    # 노트북
    '노트북', '맥북', '맥북에어', '맥북프로',
    # 냉장고
    '냉장고', '김치냉장고', '양문형냉장고',
    # 소파
    '소파', '쇼파',
    # 운동화
    '러닝화', '트레이닝화', '축구화', '농구화',
    # 청소기
    '로봇청소기', '무선청소기', '스팀청소기',
    # 헤드폰
    '헤드폰', '이어폰', '에어팟', '헤드셋',
    # 수영복
    '래쉬가드', '비키니', '원피스수영복', 'jammers',
    # 기타
    '텐트', '침낭', '버너',
}


# ─────────────────────────────────────────
# 라우터 메인 함수
# ─────────────────────────────────────────
def route(query: str) -> dict:
    """
    사용자 입력을 분석해서 어느 구역으로 보낼지 결정

    반환값:
    {
        'zone': '0' | '2' | '3' | 'direct' | 'solution',
        'mode': 'brand_ask' | 'context' | 'board' | 'trend' | 'solution',
        'product': str,       # 감지된 제품명
        'brand': str,         # 감지된 브랜드
        'context': str,       # 감지된 Context
        'solution': str,      # Solution Mode 취미명
        'message': str,       # 0구역 되물음 멘트
        'items': list,        # Solution Mode 필요 아이템
    }
    """
    q = query.strip()
    q_lower = q.lower()

    result = {
        'zone': '3',
        'mode': 'board',
        'product': '',
        'brand': '',
        'context': '',
        'solution': '',
        'message': '',
        'items': [],
    }

    # ── 1. 트렌드 키워드 감지 → Direct Mode
    for kw in TREND_KEYWORDS:
        if kw in q:
            result['zone'] = 'direct'
            result['mode'] = 'trend'
            result['product'] = q
            return result

    # ── 2. Solution Mode 감지 (취미/활동)
    for activity, triggers in _get_activity_triggers():
        if activity in q:
            for trigger in SOLUTION_TRIGGERS:
                if trigger in q:
                    result['zone'] = 'solution'
                    result['mode'] = 'solution'
                    result['solution'] = activity
                    result['message'] = SOLUTION_COPIES.get(activity, '함께 준비해요! 😊')
                    result['items'] = SOLUTION_KEYWORDS.get(activity, [])
                    return result

    # ── 3. 브랜드 감지
    detected_brand = _detect_brand(q)
    if detected_brand:
        result['brand'] = detected_brand
        # 브랜드만 입력 → 0구역 되물음
        product_after_brand = q.replace(detected_brand, '').strip()
        if not product_after_brand or len(product_after_brand) < 2:
            from price_config import BRAND_GREETINGS
            result['zone'] = '0'
            result['mode'] = 'brand_ask'
            result['message'] = BRAND_GREETINGS.get(
                detected_brand,
                BRAND_GREETINGS['default']
            )
            return result

    # ── 4. 브랜드 + 카테고리 → 2구역
    BRAND_WIDE_CATEGORIES = [
        '주방용품', '청소용품', '욕실용품', '생활용품', '문구',
        '가구', '거실가구', '침실가구', '주방가구',
        '전자제품', '가전', '의류', '신발', '식품',
    ]
    if detected_brand:
        for cat in BRAND_WIDE_CATEGORIES:
            if cat in q:
                result['zone'] = '2'
                result['mode'] = 'brand_category'
                result['product'] = cat
                return result

    # ── 5. 대분류 감지 → 2구역 2단계
    for large, subs in LARGE_CATEGORY.items():
        if large in q:
            result['zone'] = '2'
            result['mode'] = 'large_category'
            result['product'] = large
            result['items'] = subs
            return result

    # ── 6. 소분류/명확 제품 감지 → 3구역 직행
    for prod in DIRECT_PRODUCTS:
        if prod in q:
            result['zone'] = '3'
            result['mode'] = 'board'
            result['product'] = prod
            return result

    # ── 6. Context 키워드 감지 (가정/사무실/업소/성별)
    context = _detect_context(q)
    if context:
        result['zone'] = '2'
        result['mode'] = 'context'
        result['context'] = context

    # ── 7. 기본 → 3구역
    result['product'] = q
    return result


# ─────────────────────────────────────────
# 헬퍼 함수
# ─────────────────────────────────────────
def _detect_brand(query: str) -> str:
    """브랜드 감지"""
    for brand in BRANDS:
        if brand in query:
            return brand
    return ''


def _detect_context(query: str) -> str:
    """Context 키워드 감지"""
    context_map = {
        '가정': ['가정', '집', '가정용', '가족'],
        '사무실': ['사무실', '회사', '사무용', '오피스'],
        '업소': ['업소', '식당', '카페', '상업용'],
        '남성': ['남성', '남자', '남자용', '남'],
        '여성': ['여성', '여자', '여자용', '여'],
        '아동': ['아동', '아이', '어린이', '키즈', '유아'],
    }
    for context, keywords in context_map.items():
        for kw in keywords:
            if kw in query:
                return context
    return ''


def _get_activity_triggers():
    """취미/활동 키워드 목록"""
    return list(SOLUTION_KEYWORDS.items())


# ─────────────────────────────────────────
# 테스트
# ─────────────────────────────────────────
if __name__ == '__main__':
    tests = [
        '다이소',
        '다이소 주방용품 찾아줘',
        '다이소 도마 찾아줘',
        '삼성 냉장고 추천해줘',
        '러닝 시작하려고 뭐가 필요할까요',
        '베스트셀러 책 추천해줘',
        '신발 추천해줘',
        '노트북 추천해줘',
        '러닝화 찾아줘',
        '아들 운동화 찾아줘',
        '이케아 소파 찾아줘',
    ]
    print('=' * 50)
    for q in tests:
        r = route(q)
        print(f'입력: {q}')
        print(f'  → zone:{r["zone"]} mode:{r["mode"]} product:{r["product"]} brand:{r["brand"]}')
        if r['message']:
            print(f'  → 멘트: {r["message"]}')
        print()
