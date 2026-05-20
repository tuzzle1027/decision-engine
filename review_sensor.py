# ===============================
# review_sensor.py
# 픽코 리뷰 전용 감지 센서
# 동현님 설계 / 로드 구현
# ===============================
#
# sensor_layer는 구매 대화 전용
# 리뷰 텍스트는 패턴이 다름
# → 리뷰 전용 키워드 딕셔너리로 분석
#
# 10개 실제 리뷰 분석으로 만든 키워드
# ===============================

import re

# ── 긍정 키워드 ──
POSITIVE_KEYWORDS = [
    '만족', '깔끔', '대박', '감동', '완벽', '좋아요', '좋습니당', '좋아요',
    '추가구매', '재구매', '드디어', '맘에듭니다', '편리', '편해요', '편하네요',
    '확실히 편', '잘했어요', '흥미가 생긴', '킥이에요', '너무 좋아',
    '너무 맘에', '정말 좋', '최고', '강추', '추천', '대만족', '완전 좋',
    '오래 고민', '찾고 찾다가', '드디어 발견', '기대 이상', '기대초과',
]

# ── 부정 키워드 ──
NEGATIVE_KEYWORDS = [
    '실망', '매우실망', '최악', '별로', '아쉽', '아쉬워',
    '불편', '불량', '찍힘', '긁힘', '파손', '불만',
    '어렵네요', '힘들어요', '생각보다 좁', '생각보다 작',
    '환불', '반품', '교환요청', '다시는',
]

# ── BUT 패턴 (앞부정 → 뒤긍정) ──
# "배송은 늦었지만 제품은 만족" → 뒤만 긍정 처리
BUT_PATTERNS = ['이지만', '인데', '하지만', '지만', '그러나', '근데']

# ── 색상 경고 ──
COLOR_WARNING_KEYWORDS = [
    '생각보다 밝', '생각보다 어두', '아이보리 섞',
    '이렇게 밝은', '상세페이지랑 달라', '색상 달라',
    '색상 차이', '색이 달라', '색깔이 달라',
    '사진이랑 달라', '실물이 달라', '화이트인줄',
]

# ── 배송 경고 ──
DELIVERY_WARNING_KEYWORDS = [
    '배송 늦', '배송이 늦', '늦은감', '오래 걸',
    '2주', '3주', '한달', '배송 오래',
]

# ── 안전 긍정 태그 ──
SAFETY_KEYWORDS = [
    '모서리 없이', '뾰족하지 않', '안전', 'KC인증',
    '넘어지지 않도록', '잡고 일어서도', '아이 안전',
]

# ── 자세/효과 태그 ──
POSTURE_KEYWORDS = [
    '허리 펴', '허리를 펴', '꼿꼿하게', '구부정',
    '자세 좋아', '허리 잘피', '스스로 앉아',
]

# ── 디자인 만족 태그 ──
DESIGN_KEYWORDS = [
    '킥이에요', '날개부분', '홈 있는거', '콤비하길 잘',
    '고민했는데 잘', '디자인 좋', '예쁘다', '예뻐요',
    '인테리어', '감성',
]

# ── 광고성 블로그 감지 ──
AD_PATTERNS = [
    '협찬', '제공받아', '무상으로', '체험단', '리뷰어',
    '모니터링', '공식블로그', '브랜드 제공',
]


def analyze_review(text: str) -> dict:
    """
    리뷰 텍스트 분석
    
    반환:
    {
        'score':     종합 점수 (-3 ~ +3)
        'positive':  긍정 강도 (0.0~1.0)
        'negative':  부정 강도 (0.0~1.0)
        'warnings':  ['색상경고', '배송경고']
        'tags':      ['안전', '자세효과', '디자인']
        'is_genuine': 광고 아닌 진짜 리뷰 여부
        'but_pattern': BUT 패턴 감지 여부
    }
    """
    t = text.lower()

    # ── 광고성 감지 ──
    is_ad = any(kw in t for kw in AD_PATTERNS)

    # ── BUT 패턴 처리 ──
    has_but = any(kw in t for kw in BUT_PATTERNS)
    if has_but:
        # BUT 뒤만 분석
        for pattern in BUT_PATTERNS:
            if pattern in t:
                idx = t.index(pattern) + len(pattern)
                t = t[idx:]
                break

    # ── 긍정/부정 점수 ──
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in t)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in t)

    # 정규화 (0.0~1.0)
    positive = min(pos_count / 3.0, 1.0)
    negative = min(neg_count / 2.0, 1.0)

    # 종합 점수 (-3~+3)
    score = round(min(max(pos_count - neg_count * 1.5, -3), 3), 1)

    # ── 경고 태그 ──
    warnings = []
    full_text = text.lower()  # 원문으로 경고 체크
    if any(kw in full_text for kw in COLOR_WARNING_KEYWORDS):
        warnings.append('색상경고')
    if any(kw in full_text for kw in DELIVERY_WARNING_KEYWORDS):
        warnings.append('배송경고')

    # ── 긍정 태그 ──
    tags = []
    if any(kw in full_text for kw in SAFETY_KEYWORDS):
        tags.append('안전')
    if any(kw in full_text for kw in POSTURE_KEYWORDS):
        tags.append('자세효과')
    if any(kw in full_text for kw in DESIGN_KEYWORDS):
        tags.append('디자인')

    return {
        'score':      score,
        'positive':   round(positive, 2),
        'negative':   round(negative, 2),
        'warnings':   warnings,
        'tags':       tags,
        'is_genuine': not is_ad,
        'but_pattern': has_but,
    }


def analyze_reviews_batch(reviews: list) -> dict:
    """
    여러 리뷰 일괄 분석 → 종합 결과

    reviews: [{'text': '...', 'source': '...', 'url': '...'}, ...]
    """
    results = []
    total_score = 0
    all_warnings = {}
    all_tags = {}
    genuine_count = 0

    for r in reviews:
        text = r.get('text', '')
        if not text or len(text) < 10:
            continue

        result = analyze_review(text)
        result['source'] = r.get('source', '')
        result['url'] = r.get('url', '')
        result['text'] = text[:100]
        results.append(result)

        if result['is_genuine']:
            total_score += result['score']
            genuine_count += 1

        for w in result['warnings']:
            all_warnings[w] = all_warnings.get(w, 0) + 1

        for tag in result['tags']:
            all_tags[tag] = all_tags.get(tag, 0) + 1

    avg_score = round(total_score / genuine_count, 2) if genuine_count > 0 else 0

    # 매칭 점수 (0~100)
    match_score = min(int((avg_score + 3) / 6 * 100), 100)

    return {
        'reviews':      results,
        'avg_score':    avg_score,
        'match_score':  match_score,
        'warnings':     all_warnings,   # {'색상경고': 2, '배송경고': 1}
        'tags':         all_tags,       # {'안전': 3, '자세효과': 2}
        'genuine_count': genuine_count,
        'total_count':  len(results),
    }


# ── 테스트 ──
if __name__ == '__main__':
    test_reviews = [
        {'text': '어머어머 진짜 너무 맘에 들고 대박쓰! 마감 너무 깔끔쓰... 집 가구 중 제일 밝아요! 색상 달라요!', 'source': '네이버블로그'},
        {'text': '배송은 다소 늦은감이있지만 깔끔하고 만족스럽습니다 ㅎㅎ', 'source': '네이버블로그'},
        {'text': '아기들이 사용하는 제품이라 그런지 뾰족한 모서리 없이 너무 좋아요! 잡고 일어서도 넘어지지 않도록 설계된거같아요~!', 'source': '네이버블로그'},
        {'text': '실망 매우실망... 화이트인줄 알았는데 아이보리 섞였어요 찍힘도 있어요', 'source': '네이버블로그'},
        {'text': '허리를 꼿꼿하게 피고 보네요 ㅎㅎ 책에 흥미가 더 생긴 것 같아요', 'source': '네이버블로그'},
    ]

    print("=" * 55)
    print("📊 review_sensor.py 테스트")
    print("=" * 55)

    result = analyze_reviews_batch(test_reviews)

    print(f"\n총 {result['total_count']}개 / 진짜 리뷰 {result['genuine_count']}개")
    print(f"평균 점수: {result['avg_score']}")
    print(f"매칭 점수: {result['match_score']}/100")
    print(f"경고: {result['warnings']}")
    print(f"태그: {result['tags']}")

    print("\n개별 리뷰:")
    for r in result['reviews']:
        print(f"  [{r['score']:+.1f}] {r['text'][:40]}...")
        if r['warnings']: print(f"       ⚠️  {r['warnings']}")
        if r['tags']:     print(f"       ✅ {r['tags']}")
        if r['but_pattern']: print(f"       BUT패턴 감지")
