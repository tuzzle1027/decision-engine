# ============================================
# trust_layer.py — 픽코 제품 센서
# "시간이 증명 / 제품이 스스로 증명"
# ============================================
# T_final = MAX(T × (1 - penalty), Q)
# T = (P×0.4) + (C×0.3) + (R×0.2) + (V×0.1)
# ============================================

from datetime import datetime, date


# ── 재구매 신호 키워드 ──
REBUYING_KEYWORDS = ['또 샀', '재구매', '몇번째', '단골', '두번째', '세번째', '계속 사']

# ── 감탄 언어 키워드 (Q 변수) ──
# "나만 알고 싶은데 알려주고 싶은" 그 감정
Q_KEYWORDS = ['신의한수', '이게 되네', '왜 이제 알았지', '진작 살걸',
              '없으면 어떻게', '강추', '인생템', '오~~~', '대박', '실화냐']

# ── 부정 신호 키워드 ──
NEGATIVE_KEYWORDS = ['별로', '실망', '후회', '반품', '교환', '불량', '망가', '환불']


def calculate_T(blog_posts: list) -> dict:
    """
    블로그 포스팅 목록을 받아 제품 신뢰 지수 계산

    blog_posts 형식:
    [
        {
            'text': '...',          # 200자 본문
            'full_text': '...',     # 500자 본문 (있으면 더 정확)
            'postdate': '20240315', # 날짜 (YYYYMMDD)
            'bloggername': '...',
            'url': '...',
            'source': '네이버 블로그'
        },
        ...
    ]
    """

    empty = {
        'P': 0, 'C': 0, 'R': 0, 'V': 0, 'Q': 0,
        'T_raw': 0, 'penalty': 0, 'T_final': 0,
        'verdict': '정보 부족',
        'badge': None, 'story': '',
        'months': 0, 'total_posts': 0,
        'rebuy_count': 0, 'q_count': 0, 'neg_count': 0,
    }

    if not blog_posts:
        return empty

    today = date.today()
    dates = []
    for post in blog_posts:
        pd = post.get('postdate', '')
        if len(pd) == 8:
            try:
                dates.append(datetime.strptime(pd, '%Y%m%d').date())
            except:
                continue

    if not dates:
        return empty

    total = len(blog_posts)   # ★ 전체 후기 수 (postdate 없어도 포함!)
    dated = len(dates)        # ★ 날짜 있는 후기 수 (P/C 계산용)
    earliest = min(dates)
    months = (today.year - earliest.year) * 12 + (today.month - earliest.month)

    # ── P: 판매기간 ──
    P = 1.0 if months >= 24 else 0.8 if months >= 12 else 0.5 if months >= 6 else 0.2

    # ── V: 볼륨 (전체 후기 수 기준) ──
    V = 1.0 if total >= 50 else 0.7 if total >= 20 else 0.4 if total >= 10 else 0.2 if total >= 5 else 0.1

    # ── C: 일관성 (분기별 분포) ──
    quarters = set()
    for d in dates:
        quarters.add((d.year, (d.month - 1) // 3))
    eq = max(1, (today.year - earliest.year) * 4 + (today.month - 1) // 3 - (earliest.month - 1) // 3 + 1)
    empty_q = max(0, eq - len(quarters))
    C = 1.0 if empty_q == 0 else 0.7 if empty_q <= 2 else 0.3

    # ── R: 재구매 신호 ──
    rebuy_count = sum(
        1 for p in blog_posts
        if any(kw in (p.get('full_text') or p.get('text', '')) for kw in REBUYING_KEYWORDS)
    )
    R_ratio = rebuy_count / total
    R = 1.0 if R_ratio >= 0.1 else 0.6 if R_ratio >= 0.05 else 0.2

    # ── Q: 감탄 언어 (숨은 명품 신호) ──
    q_count = sum(
        1 for p in blog_posts
        if any(kw in (p.get('full_text') or p.get('text', '')) for kw in Q_KEYWORDS)
    )
    Q_ratio = q_count / total
    Q = 1.0 if Q_ratio >= 0.1 else 0.6 if Q_ratio >= 0.05 else 0.2

    # ── 부정 신호 ──
    neg_count = sum(
        1 for p in blog_posts
        if any(kw in (p.get('full_text') or p.get('text', '')) for kw in NEGATIVE_KEYWORDS)
    )

    # ── 군중심리 패널티 ──
    m = today.month - 3
    y = today.year
    if m <= 0:
        m += 12
        y -= 1
    try:
        three_ago = date(y, m, 1)
    except:
        three_ago = date(today.year - 1, today.month, 1)

    recent = sum(1 for d in dates if d >= three_ago)
    penalty = 0.4 if (total > 0 and recent / total >= 0.5 and (total - recent) <= 2) else 0

    # ── T 계산 ──
    T_raw = round((P * 0.4) + (C * 0.3) + (R * 0.2) + (V * 0.1), 2)
    T_final = round(max(T_raw * (1 - penalty), Q), 2)

    verdict = '검증된 제품' if T_final >= 0.8 else '참고 필요' if T_final >= 0.5 else '정보 부족'

    return {
        'P': round(P, 2), 'C': round(C, 2), 'R': round(R, 2),
        'V': round(V, 2), 'Q': round(Q, 2),
        'T_raw': T_raw, 'penalty': penalty, 'T_final': T_final,
        'verdict': verdict,
        'badge': None,          # get_badge()에서 결정
        'story': '',            # get_trust_story()에서 생성
        'months': months,
        'total_posts': total,
        'rebuy_count': rebuy_count,
        'q_count': q_count,
        'neg_count': neg_count,
    }


def get_badge(trust: dict) -> str | None:
    """
    trust_layer 결과로 뱃지 결정
    None이면 섹션 숨김
    """
    T       = trust['T_final']
    Q       = trust['Q']
    penalty = trust['penalty']
    months  = trust['months']
    total   = trust['total_posts']
    rebuy   = trust['rebuy_count']

    # 우선순위 순
    if penalty >= 0.4 and months <= 6:
        return '신제품'

    if penalty >= 0.4 and months > 6:
        return '행사 주의'

    if Q >= 0.6 and total < 20:
        return '숨은 명품'

    if T >= 0.8 and months >= 24:
        return '스테디셀러'

    if T >= 0.8:
        return '검증된 제품'

    if T >= 0.6 and months >= 12:
        return '꾸준한 인기'       # ★ 새 뱃지

    if rebuy >= 1 and months >= 6:
        return '재구매 있음'       # ★ 새 뱃지

    if months >= 24 and total >= 5:
        return '오래된 제품'       # ★ 새 뱃지 (오래됐지만 후기 적음)

    # 조건 미달 → 섹션 숨김
    return None


def build_trust_prompt(trust: dict, badge: str) -> str:
    """
    LLM에 넘길 프롬프트 생성
    picko_summary LLM 호출에 추가하면 됨
    """
    return f"""
[시장 데이터 — 제품 센서 결과]
뱃지: {badge}
판매기간: {trust['months']}개월
블로그 후기: {trust['total_posts']}건
재구매 언급: {trust['rebuy_count']}건
감탄 표현: {trust['q_count']}건
부정 언급: {trust['neg_count']}건
군중심리 패널티: {'있음' if trust['penalty'] else '없음'}
T_final: {trust['T_final']}

위 데이터를 보고 사용자에게 2문장으로 전달하세요.
규칙:
- 수치를 직접 쓰지 말고 의미로 풀어주세요
- 사용자가 "오~~~ 몰랐네!" 반응이 나오도록
- 판단 결과만 말하지 말고 발견을 전달하세요
- 따뜻하고 짧게 (2문장)
"""
