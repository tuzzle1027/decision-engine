# ===============================
# review_builder.py
# 리뷰 분석 / 생성 전담 모듈
# recommendation.py에서 분리
# ===============================
#
# 포함:
#   build_user_context()         ← 사용자 맥락 생성 (LLM 전달용)
#   AXIS_KEYWORDS             ← 6축 키워드 매핑
#   EXCLUDE_PATTERNS          ← 광고/공구 필터
#   GENUINE_REVIEW_KEYWORDS   ← 진짜 후기 판별 키워드
#   _detect_axis()            ← 6축 감지
#   _calc_review_score()      ← 키워드 기반 점수 계산
#   _score_to_stars()         ← 점수 → 별점
#   _build_picko_ratings()    ← 픽코 평점 3개 생성
#   _extract_relevant_text()  ← 타 브랜드 문장 제거
#   _refine_review()          ← LLM으로 1문장 압축
#   _build_user_voices()      ← 좋은/나쁜 후기 선별
#   _build_picko_summary()    ← 픽코 총평
#   _extract_kill_point()     ← 킬 포인트 추출
#   _build_emotional_reason() ← 감성 설득 문구
# ===============================


def build_user_context(product_name: str, selections: str, direct_input: str = '') -> str:
    """
    사용자 맥락 생성 - 모든 LLM 호출에 전달
    "이 사람이 뭘 원하는지" LLM이 알게 해줌

    예:
    → "3인용 패브릭 소파를 찾는 사람 / 직선형 헤드틸팅 스툴포함 아이보리 선택 / 배송 날짜 중요"
    """
    # 상황판 선택 요약
    sel_parts = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', 'E'] and v:
                sel_parts.append(v)

    context_parts = [f'{product_name} 구매 예정']
    if sel_parts:
        context_parts.append(f'선택조건: {" ".join(sel_parts[:5])}')
    if direct_input:
        context_parts.append(f'직접요청: {direct_input}')

    return ' / '.join(context_parts)


# ── 6축 키워드 매핑 ──
AXIS_KEYWORDS = {
    'C1': ['안전', 'KC', '아이', '독성', '친환경', '무독성', '어린이'],
    'C2': ['기능', '세탁', '방수', '커버분리', '성능', '내구성', '튼튼', '품질'],
    'C4': ['배송', '도착', '빠름', '느림', '택배', '설치', '배달'],
    'C5': ['가격', '비싸', '저렴', '가성비', '돈값', '합리적'],
}

# 제외할 패턴 (공구/광고/협찬/링크광고)
EXCLUDE_PATTERNS = [
    '공구', '공동구매', '협찬', '제공받', '광고', '체험단',
    '모니터링', '소정의', '원고료', '이벤트 당첨',
    'naver.me', 'link.coupang', '버튼 클릭', '버튼 누르',
    '확인하세요', '놓치면 후회', '시간 아끼', '바로 확인',
    '아래 버튼', '전부 공개', '쿠팡 파트너스',
    # ★ 청소/서비스 업체 차단 (강아지 털 검색 시 범람!)
    '소파청소', '소파 청소', '클리닝 후기', '홈케어',
    '소파세탁', '소파 세탁', '케어서비스', '얼룩제거',
    '소파클리닝', '방문청소', '살균소독',
]

# 진짜 후기 판별 - 갈등/고민 키워드 (센서 연결!)
GENUINE_REVIEW_KEYWORDS = {
    'C1_안전': ['안전', 'KC인증', '독성', '아이', '유아', '친환경', '무독성'],
    'C2_기능': ['방수', '밀리지', '떨어지지', '각도', '조절', '내구성', '튼튼'],
    'C4_배송': ['배송', '빨리왔', '늦게왔', '도착', '설치'],
    'C5_가격': ['가성비', '비싸지만', '저렴', '가격대비', '망설', '고민'],
    'C6_비교': ['비교', '다른제품', '고민하다', '찾아보다', '여러개'],
    '갈등':    ['망설였', '고민했', '살까말까', '신중', '찾아보다', '여러'],
}


def _detect_axis(text):
    """텍스트에서 6축 감지"""
    for axis, keywords in AXIS_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return axis
    return None


def _calc_review_score(reviews, keywords):
    """키워드 기반 긍정/부정 분석 → 점수(0~100)"""
    if not reviews:
        return 0, 0

    POS = ['좋아', '만족', '완벽', '최고', '추천', '빠르', '튼튼', '예뻐', '대박', '훌륭', '편해']
    NEG = ['별로', '나빠', '실망', '느려', '깨져', '불만', '아쉬워', '거칠', '약해', '비싸', '오래']

    matched = [r for r in reviews if any(kw in r['text'] for kw in keywords)]
    if not matched:
        matched = reviews

    pos = sum(1 for r in matched if any(p in r['text'] for p in POS))
    neg = sum(1 for r in matched if any(n in r['text'] for n in NEG))
    total = len(matched)

    score = int((pos / total) * 100) if total > 0 else 50
    return score, total


def _score_to_stars(score):
    """점수 → 별점"""
    if score >= 90: return '★★★★★'
    if score >= 70: return '★★★★☆'
    if score >= 50: return '★★★☆☆'
    if score >= 30: return '★★☆☆☆'
    return '★☆☆☆☆'


def _build_picko_ratings(reviews, selections='', extra=''):
    """픽코 평점 고정 3개 (배송/품질/만족도)"""

    FIXED_RATINGS = [
        {
            'label': '배송',
            'keywords': ['배송', '도착', '빠름', '느림', '택배', '수령', '빠르'],
        },
        {
            'label': '품질',
            'keywords': ['튼튼', '내구', '품질', '마감', '견고', '약해', '부러', '오래'],
        },
        {
            'label': '만족도',
            'keywords': ['만족', '좋아', '추천', '실망', '후회', '기대', '별로', '최고'],
        },
    ]

    # 공구/광고 필터링 먼저
    clean_reviews = [r for r in reviews if not any(ex in r['text'] for ex in EXCLUDE_PATTERNS)]
    if not clean_reviews:
        clean_reviews = reviews

    ratings = []
    for item in FIXED_RATINGS:
        score, _ = _calc_review_score(clean_reviews, item['keywords'])

        # 키워드 주변 20자만 추출
        sample = ''
        for r in clean_reviews:
            if any(kw in r['text'] for kw in item['keywords']):
                text = r['text']
                for kw in item['keywords']:
                    idx = text.find(kw)
                    if idx >= 0:
                        start = max(0, idx - 5)
                        end = min(len(text), idx + 15)
                        sample = text[start:end].strip()
                        break
                if sample:
                    break

        ratings.append({
            'badge': '기본',
            'label': item['label'],
            'quote': sample,
            'stars': _score_to_stars(score),
            'pct': score,
        })

    return ratings


def _extract_relevant_text(raw_text, brand_filter):
    """타 브랜드 문장 제거 (브랜드 언급 없는 문장은 유지!)"""
    if not brand_filter:
        return raw_text[:200]

    # 유명 소파/가구 브랜드 목록 (이 브랜드 언급 문장 제거!)
    KNOWN_BRANDS = [
        '까사미아', '삼익가구', '한샘', '이케아', '리바트', '일룸',
        '에싸', '에몬스', '보니애가구', '오스본가구', '헤이미쉬홈',
        '라라홈', '듀커', '브리엔츠', '세인트블랑', '웰퍼니쳐',
        '홈앤힐', '안다가구', '버즈가구', '퍼니챗', '라자가구',
        '퍼피노', '시스디자인', '자코모', '슬로우알레', '알로소',
        '라움', '도미르베네', '샷츠', '크루저', '채우리', '아인스미',
        '핀란디아', '마켓비', '다즐', '스파지오', '로코코', '반트',
        '썸앤데코', '루피나', '인터라켄', '페다', '베니시모',
    ]
    # 현재 제품 브랜드는 제거 목록에서 빼기
    other_brands = [b for b in KNOWN_BRANDS if b.lower() != brand_filter.lower()]

    import re as _re_sent
    sentences = _re_sent.split(r'[.!?。]', raw_text)

    filtered = []
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 5:
            continue
        if any(b in s for b in other_brands):
            continue
        filtered.append(s)

    if filtered:
        return '. '.join(filtered[:4])
    return raw_text[:100]


def _refine_review(raw_text, bloggername, call_llm_fn=None, brand_filter='', match_keywords=None, user_context=''):
    """관련 문장 추출 후 LLM으로 1문장 압축 - 사용자 맥락 + 조건 키워드 중심으로!"""
    if not call_llm_fn:
        return raw_text[:40]
    try:
        relevant_text = _extract_relevant_text(raw_text, brand_filter)

        brand_rule = (
            f'\n- 반드시 [{brand_filter}] 제품 후기만! 타 브랜드 절대 금지!'
            if brand_filter else ''
        )

        # 사용자 맥락 전달 → LLM이 뭘 살려야 하는지 앎!
        context_rule = f'\n- 구매자 상황: {user_context}' if user_context else ''

        # 조건 키워드 있으면 → 그 내용 중심으로 압축!
        keyword_rule = ''
        if match_keywords:
            kw_str = ', '.join(match_keywords[:5])
            keyword_rule = f'\n- [{kw_str}] 관련 내용이 있으면 반드시 그 내용 중심으로!'

        prompt = (
            '아래 후기를 자연스러운 구어체 1문장(30자 이내)으로 압축해줘.\n\n'
            f'후기: {relevant_text[:200]}\n\n'
            '규칙:\n'
            '- 핵심 경험/감정만\n'
            '- 내돈내산/후기 같은 말 제거\n'
            '- 실제 사용자 말투\n'
            '- 1문장만 (따옴표 없이)\n'
            f'- 30자 이내{brand_rule}{context_rule}{keyword_rule}'
        )
        result = call_llm_fn(prompt, max_tokens=60).strip()
        result = result.replace('"', '').replace("'", '')
        REJECT_KW = ['죄송', '제공하신', '후기에는', '없습니다', '찾을 수 없', '제품명과 가격']
        if any(kw in result for kw in REJECT_KW):
            return ''
        return result
    except:
        return raw_text[:40]


def _build_user_voices(reviews, extra='', call_llm_fn=None, brand_filter='', match_keywords=None, user_context=''):
    """
    키워드 매칭 후기 우선 선별 + 볼드용 keywords 필드 추가
    match_keywords: 상황판 + 직접입력에서 추출한 핵심 키워드
    user_context: 사용자 맥락 (LLM 압축 시 전달)
    → 키워드 포함 후기 우선 선별 → 사용자가 원하는 내용 보여줌!
    """
    POS = ['좋아', '만족', '완벽', '최고', '추천', '빠르', '튼튼', '예뻐', '대박', '편해', '꼼꼼', '무해', '안전']
    NEG = ['별로', '실망', '느려', '불만', '아쉬워', '거칠', '약해', '오래', '늦게', '걸렸', '기다', '아쉽']
    match_keywords = match_keywords or []

    # 공구/광고 필터링
    clean = [r for r in reviews if not any(ex in r['text'] for ex in EXCLUDE_PATTERNS)]
    if not clean:
        clean = reviews

    # ★ 키워드 매칭 후기 우선 정렬!
    # 키워드 많이 포함된 후기가 앞으로
    def _match_score(r):
        text = r['text']
        return sum(1 for kw in match_keywords if kw in text)

    if match_keywords:
        # 키워드 매칭 후기 먼저, 나머지 뒤로
        matched   = sorted([r for r in clean if _match_score(r) > 0],
                           key=_match_score, reverse=True)
        unmatched = [r for r in clean if _match_score(r) == 0]
        clean = matched + unmatched
        print(f'[키워드매칭] {match_keywords} → 매칭후기 {len(matched)}개 우선')

    # ★ R1/R2 자체몰 리뷰 분리 (vreview/크리마/한샘)
    def _is_official(r):
        return r.get('source', '').startswith('R1') or r.get('source', '').startswith('R2')

    def _get_display_source(r):
        """
        출처 표시 규칙:
        R1/R2 (공식몰) → 빈 문자열 (경쟁사에 티 안 냄, 사용자는 출처 없으면 공식몰로 인지)
        블로그/카페    → "블로거이름 · 네이버 블로그"
        """
        _src = r.get('source', '')
        if _src.startswith('R1') or _src.startswith('R2'):
            return ''  # ★ 공식몰 리뷰는 출처 숨김
        if not _src or _src == '네이버 블로그':
            return r.get('bloggername', '') + ' · 네이버 블로그'
        return _src

    # R1/R2 리뷰 → pos/neg 앞으로 강제 배치
    official_pos = [r for r in clean if _is_official(r) and any(p in r['text'] for p in POS)]
    official_neg = [r for r in clean if _is_official(r) and any(n in r['text'] for n in NEG)]
    blog_pos     = [r for r in clean if not _is_official(r) and any(p in r['text'] for p in POS)]
    blog_neg     = [r for r in clean if not _is_official(r) and any(n in r['text'] for n in NEG)]

    pos_reviews = official_pos + blog_pos  # ★ 공식몰 우선!
    neg_reviews = official_neg + blog_neg

    if official_pos:
        print(f'[R1우선] 공식몰 긍정 {len(official_pos)}개 → 앞으로!')
    if official_neg:
        print(f'[R1우선] 공식몰 부정 {len(official_neg)}개 → 앞으로!')

    # 중복 제거
    pos_urls = {r['url'] for r in pos_reviews[:2]}
    neg_reviews = [r for r in neg_reviews if r['url'] not in pos_urls]

    voices = []
    for r in pos_reviews[:2]:
        refined = _refine_review(r['text'], r.get('bloggername', ''), call_llm_fn,
                                  brand_filter=brand_filter, match_keywords=match_keywords,
                                  user_context=user_context)
        matched_kws = [kw for kw in match_keywords if kw in (refined + r['text'])]
        if not refined:
            continue
        voices.append({
            'type':     'pos',
            'text':     refined,
            'source':   _get_display_source(r),  # ★ R1/R2 = 빈 문자열
            'keywords': matched_kws,
        })

    if neg_reviews:
        r = neg_reviews[0]
        refined = _refine_review(r['text'], r.get('bloggername', ''), call_llm_fn,
                                  brand_filter=brand_filter, match_keywords=match_keywords,
                                  user_context=user_context)
        matched_kws = [kw for kw in match_keywords if kw in (refined + r['text'])]
        if refined:
            voices.append({
                'type':     'neg',
                'text':     refined,
                'source':   _get_display_source(r),  # ★ R1/R2 = 빈 문자열
                'keywords': matched_kws,
            })
    elif len(pos_reviews) >= 3:
        r = pos_reviews[2]
        refined = _refine_review(r['text'], r.get('bloggername', ''), call_llm_fn,
                                  brand_filter=brand_filter, match_keywords=match_keywords,
                                  user_context=user_context)
        matched_kws = [kw for kw in match_keywords if kw in (refined + r['text'])]
        if refined:
            voices.append({
                'type':     'pos',
                'text':     refined,
                'source':   _get_display_source(r),  # ★ R1/R2 = 빈 문자열
                'keywords': matched_kws,
            })
        print('[후기] 나쁜 후기 없음 → 좋은 후기로 대체')

    # 빈 후기/거절 메시지 제거
    voices = [v for v in voices if v.get('text') and len(v.get('text', '')) > 3]
    return voices


def _build_picko_summary(product_name, reviews, extra='', call_llm_fn=None, user_context=''):
    """픽코 총평 - 사용자 맥락 중심으로!"""
    if not reviews or not call_llm_fn:
        return ''

    review_texts = '\n'.join([f'- {r["text"][:100]}' for r in reviews[:8]])
    axis = _detect_axis(extra) if extra else None
    axis_names = {'C1': '안전성', 'C2': '품질/기능', 'C4': '배송', 'C5': '가격/가성비'}
    focus = f'특히 [{axis_names.get(axis, "")}] 관련 후기를 중심으로' if axis else '전반적으로'

    # 사용자 맥락 전달!
    context_str = f'\n구매자 상황: {user_context}' if user_context else ''

    prompt = f"""{product_name} 실제 블로그 후기예요:{context_str}
{review_texts}

{focus} 2문장으로 총평해주세요.

규칙:
- "후기 읽어봤어요 😊"로 시작
- 장점 1개 + 단점/주의사항 1개 포함
- 구매자 상황에 맞는 내용 우선!
- 친근하고 솔직하게
- 광고 느낌 절대 금지
- 마지막 문장은 반드시 긍정적으로 마무리
- 2문장만 출력

★★ 절대 금지 (위반 시 신뢰 붕괴!):
- 후기에 없는 내용 절대 금지!
- "TV광고", "유명한", "인기 있는" 등
  검증 불가 표현 절대 금지!
- 사용자 직접입력 조건을
  제품 특징인 것처럼 서술 금지!
- 후기가 부족하면:
  "후기가 충분하지 않아 솔직히
   말씀드리기 어려워요 😔
   구매 전 상세페이지를 꼭 확인하세요!"
  → 이렇게 솔직하게 말할 것!"""

    try:
        result = call_llm_fn(prompt, max_tokens=150)
        return result.strip()
    except Exception as e:
        print(f'[총평오류] {e}')
        return ''


def _extract_kill_point(reviews, call_llm_fn=None, user_context=''):
    """후기에서 킬 포인트(독보적 장점) 추출 - 사용자 맥락 중심!"""
    if not call_llm_fn or not reviews:
        return ''
    review_text = ' / '.join([r['text'][:80] for r in reviews[:10]])

    context_str = f'\n구매자 상황: {user_context}\n→ 이 상황에 맞는 킬포인트 우선!' if user_context else ''

    prompt = (
        f'후기들:\n{review_text}\n{context_str}\n\n'
        '이 제품의 가장 독보적인 장점 1가지를 20자 이내로 뽑아줘.\n'
        '규칙:\n'
        '- 구매자 상황에 맞는 장점 우선!\n'
        '- "~해요" 말투\n'
        '- 1문장만 출력\n'
        '- 마크다운 금지'
    )
    try:
        result = call_llm_fn(prompt, max_tokens=50).strip()
        REJECT_KW = ['죄송', '없습니다', '제공하신', '찾을 수 없', '제품명과 가격']
        if any(kw in result for kw in REJECT_KW):
            return ''
        return result
    except:
        return ''



def _build_emotional_reason(product_name, selections, extra='', call_llm_fn=None, reviews=None):
    """이런 점이 마음에 드실 거예요 (킬 포인트 우선, 없으면 감성 설득)"""
    if not call_llm_fn:
        return ''

    kill_point = _extract_kill_point(reviews or [], call_llm_fn)

    CATEGORY_PHILOSOPHY = {
        '소파': '소파 하나가 바뀌면 거실이 달라 보이고, 집에 돌아오는 발걸음이 가벼워져요.',
        '침대': '잠드는 공간이 달라지면, 아침에 눈 뜨는 기분부터 달라져요.',
        '책상': '앉아야 뭔가를 시작할 수 있어요. 좋은 자리가 좋은 시작을 만들어요.',
        '의자': '하루 중 가장 오래 함께하는 것이 의자예요. 몸이 편해야 생각도 자유로워져요.',
        '옷장': '아침에 옷 고르는 시간이 달라지면, 하루를 시작하는 마음이 달라져요.',
        '독서대': '아이가 책을 펼치는 자리가 생기면, 읽는 습관이 저절로 따라와요.',
    }

    philosophy = ''
    for cat, phil in CATEGORY_PHILOSOPHY.items():
        if cat in product_name:
            philosophy = phil
            break

    user_need = extra if extra else ''

    if kill_point:
        prompt = f"""제품: [{product_name}]
사용자들이 공통으로 말하는 핵심 장점: {kill_point}

이 핵심 장점을 자연스럽게 녹여서 2문장을 써주세요.

규칙:
- 핵심 장점이 왜 실제 생활에서 중요한지 공감 먼저
- "사세요" "구매하세요" 절대 금지
- 기능 나열 금지
- 사용자가 스스로 "맞아, 이게 필요해" 느끼게
- 2문장만 출력"""
    else:
        prompt = f"""사용자가 [{product_name}]을 찾고 있어요.
사용자 니즈: {user_need if user_need else '편안하고 만족스러운 구매'}

아래 철학을 참고해서 2문장을 써주세요:
철학: {philosophy if philosophy else '좋은 제품 하나가 일상을 바꿔요.'}

규칙:
- 제품 색상/사이즈/소재 언급 절대 금지
- "사세요" "구매하세요" 절대 금지
- 기능 설명 금지
- 사용자가 이 제품을 왜 '지금' 필요한지 스스로 깨닫게
- 2문장만 출력"""

    try:
        result = call_llm_fn(prompt, max_tokens=120)
        return result.strip()
    except Exception as e:
        print(f'[감성설득오류] {e}')
        return ''


def _build_pros_cons_oneline(product_name, reviews, selections='', call_llm_fn=None):
    """
    블로그 후기에서 한 번에 추출:
    - 좋다는 말 / 아쉽다는 말 / 픽코 한마디
    - 실구매가 / 공구여부 / 실사용상황 / 장기사용
    """
    if not reviews or not call_llm_fn:
        return [], [], '', {}, [], ''

    texts = [r.get('full_text') or r.get('text', '') for r in reviews[:12] if r.get('text')]
    texts = [t[:150] for t in texts if t]
    if not texts:
        return [], [], '', {}, [], ''

    review_str = '\n'.join(f'- {t}' for t in texts)

    prompt = f"""제품: {product_name}
블로그 후기:
{review_str}

아래 형식으로만 출력하세요. 없으면 해당 줄 비워두세요.

좋다는말: 문장1|문장2|문장3
아쉽다는말: 문장1|문장2
픽코한마디: 한 줄
실구매가: 최저가~최고가 (예: 190만~230만원, 후기에 가격 언급 없으면 비워두기)
공구여부: 있음 (공구/공동구매/특가 언급 있을 때만. 없으면 비워두기)
실사용상황: 상황1|상황2 (예: 아이 있는 집|반려동물 키우는 집. 없으면 비워두기)
장기사용: 내용 (예: 1년 써도 형태 유지돼요. n개월/n년 언급 없으면 비워두기)

규칙:
- 좋다는말: 각 15자 이내, "~해요" 말투, 2~3개
- 아쉽다는말: 각 15자 이내, 1~2개
  직접적 단점 없어도 간접 표현 포함!
  예) "배송이 좀 걸려요" "색상이 사진이랑 달라요"
      "조립이 생각보다 어려워요" "기대보다 아쉬워요"
  정말 아무것도 없을 때만 비워두기
- 픽코한마디: 팩트형 결론, 20자 이내
- 모든 내용은 후기에 근거한 것만! 완전히 없으면 만들지 말 것"""

    try:
        result = call_llm_fn(prompt, max_tokens=200).strip()
        pros, cons, one_line = [], [], ''
        price_info = {}
        situations = []
        long_term = ''

        for line in result.split('\n'):
            line = line.strip()
            if line.startswith('좋다는말:'):
                raw = line.replace('좋다는말:', '').strip()
                pros = [x.strip() for x in raw.split('|') if x.strip()]
            elif line.startswith('아쉽다는말:'):
                raw = line.replace('아쉽다는말:', '').strip()
                cons = [x.strip() for x in raw.split('|') if x.strip()]
            elif line.startswith('픽코한마디:'):
                one_line = line.replace('픽코한마디:', '').strip()
            elif line.startswith('실구매가:'):
                raw = line.replace('실구매가:', '').strip()
                if raw:
                    price_info['range'] = raw
            elif line.startswith('공구여부:'):
                raw = line.replace('공구여부:', '').strip()
                if raw:
                    price_info['gonggu'] = True
            elif line.startswith('실사용상황:'):
                raw = line.replace('실사용상황:', '').strip()
                situations = [x.strip() for x in raw.split('|') if x.strip()]
            elif line.startswith('장기사용:'):
                long_term = line.replace('장기사용:', '').strip()

        print(f'[pros/cons] 좋음:{len(pros)} 아쉬움:{len(cons)} 한마디:{bool(one_line)} 가격:{bool(price_info)} 상황:{len(situations)} 장기:{bool(long_term)}')
        return pros, cons, one_line, price_info, situations, long_term

    except Exception as e:
        print(f'[pros_cons오류] {e}')
        return [], [], '', {}, [], ''


# ===============================
# 상황판 옵션 + 직접입력 → 네이버 블로그 검색어
# ===============================

# 핵심 키워드 (절대 누락 금지)
MUST_KEYS = ['인원수', '사이즈', '크기']

def build_natural_query(
    raw_product: str,
    selections: str,
    direct_input: str = '',
    call_llm_fn=None,
) -> tuple:
    """
    상황판 + 직접입력 → 자연어 블로그 검색어 2개 반환
    반환: (board_query, direct_query)

    board_query:  상황판 옵션 기반 자연어 (항상 생성)
    direct_query: 직접입력 기반 자연어 (직접입력 있을 때만)
    """
    must_vals = []
    board_sel_vals = []

    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k in MUST_KEYS and v:
                must_vals.append(v)
            elif k not in ['가격', '색상', 'E', '직접입력'] and v:
                board_sel_vals.append(v)

    product_kw = raw_product.split()[-1]
    board_query = ''
    direct_query = ''

    # ── 상황판 쿼리 (항상 생성) ──
    # ⚠️ 가격대 힌트는 미해결!
    # 가격 키워드 넣으면 광고 많아지고 상황판 옵션 사라짐
    # 나중에 해결책 찾으면 추가

    if must_vals or board_sel_vals:
        sel_str = ' '.join((must_vals + board_sel_vals)[:4])
        must_rule = f'- {", ".join(must_vals)} 반드시 포함!' if must_vals else ''
        prompt = (
            f'제품: {raw_product}\n'
            f'선택 조건: {sel_str}\n\n'
            f'이 조건으로 소파/가구를 구매한 실제 사람이\n'
            f'네이버 블로그에 검색할 법한 자연스러운 검색어를 만들어줘.\n\n'
            f'규칙:\n'
            f'{must_rule}\n'
            f'- 상품 카탈로그 언어 금지! ("헤드틸팅 패브릭 소파 추천" 같은 것 금지)\n'
            f'- 실제 구매 상황/감정이 담긴 말투\n'
            f'  예) "아이 있어서 패브릭 소파 내돈내산"\n'
            f'  예) "거실 소파 바꿨는데 솔직후기"\n'
            f'  예) "강아지 있는 집 소파 추천"\n'
            f'- "내돈내산" "솔직후기" "실사용" 중 하나 포함\n'
            f'- 5단어 이내\n'
            f'- 검색어 1줄만 출력'
        )
        try:
            if call_llm_fn:
                board_query = call_llm_fn(prompt, max_tokens=30).strip()
                board_query = board_query.split('\n')[0].strip()
                # 핵심 키워드 누락 시 강제 추가
                for mv in must_vals:
                    if mv not in board_query:
                        board_query = f'{mv} {board_query}'
                print(f'[자연어쿼리-상황판] "{board_query}"')
        except Exception:
            board_query = ' '.join(must_vals + board_sel_vals[:2]) + f' {product_kw} 내돈내산'
            print(f'[자연어쿼리-상황판폴백] "{board_query}"')

    # ── 직접입력 쿼리 (직접입력 있을 때만) ──
    if direct_input:
        # ★ 특수 기능명 목록 (시스템 작동 테스트 기준점!)
        # 언제든 이 키워드 넣으면 코드 추출로 정확하게 작동해야 함
        SPECIAL_FEATURES = [
            '양방향 입체기울기',  # 튜즐 특허 기능
        ]

        _is_special = any(feat in direct_input for feat in SPECIAL_FEATURES)

        if _is_special:
            # 특수 기능명 → 코드 추출 (LLM 변환 없이!)
            _di_kws = extract_direct_keywords(direct_input)
            direct_query = f'{" ".join(_di_kws)} {product_kw}'
            print(f'[자연어쿼리-직접입력] "{direct_query}" (특수기능!)')
        else:
            # 일반 서술 → LLM 변환 (진짜 사람언어!)
            direct_prompt = (
                f'제품: {raw_product}\n'
                f'사용자 의도: {direct_input}\n\n'
                f'이 의도로 제품을 산 실제 사람이 블로그에 검색할 법한 검색어를 만들어줘.\n'
                f'규칙:\n'
                f'- 상품 카탈로그 언어 금지! ("방수 패브릭 소파 추천" 같은 것 금지)\n'
                f'- 실제 구매 상황/감정이 담긴 말투\n'
                f'  예) "아이 있어서 방수 소파 내돈내산"\n'
                f'  예) "강아지 키우는 집 소파 솔직후기"\n'
                f'  예) "거실 소파 바꿨는데 실사용 후기"\n'
                f'- "내돈내산" "솔직후기" "실사용" 중 하나 포함\n'
                f'- 5단어 이내\n'
                f'- 검색어 1줄만 출력'
            )
            try:
                if call_llm_fn:
                    direct_query = call_llm_fn(direct_prompt, max_tokens=30).strip()
                    direct_query = direct_query.split('\n')[0].strip()
                    print(f'[자연어쿼리-직접입력] "{direct_query}"')
            except Exception:
                direct_query = f'{raw_product} {direct_input[:10]} 후기'
                print(f'[자연어쿼리-직접입력폴백] "{direct_query}"')

    return board_query, direct_query


# ===============================
# 매칭 키워드 추출
# 직접입력에서 핵심 명사만 추출
# 조사/어미 제거로 정확한 매칭!
# ===============================

def extract_match_keywords(selections: str, direct_input: str = '') -> list:
    """
    상황판 옵션 + 직접입력에서 핵심 키워드 추출
    한국어 조사/어미 제거 → 후기 매칭 정확도 향상!

    예:
    "강아지가 있는데 털이 묻지" → ['강아지', '털']
    "방수되는 소파" → ['방수', '소파']
    """
    import re as _re

    # 상황판 옵션 키워드
    match_keywords = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', '색상', 'E'] and v and len(v) > 1:
                match_keywords.append(v)

    # 직접입력 핵심 명사 추출
    if direct_input:
        # 한국어 조사/어미 제거 패턴
        JOSA_PATTERN = r'(이|가|을|를|은|는|에|에서|으로|로|와|과|도|만|부터|까지|처럼|보다|에게|한테|께|의|랑|이랑|고|서|니까|아서|어서|아도|어도|지만|지는|이라|이라서|이라도|라서|라도|이고|이며|이나|이나마|씩|마다|라면|이라면|으면|면|지|는데|은데|인데)$'

        # 불용어 (의미없는 단어)
        STOPWORDS = {
            '있어서', '없어서', '그래서', '하지만', '이라서',
            '사람이', '것이', '때문에', '정도', '중요해요',
            '골라줘요', '찾아줘요', '해줘요', '싶어요', '않았으면',
            '있는데', '없는데', '관리가', '가능한', '하기에',
            '묻지', '않아요', '됩니다', '합니다', '해주세요',
            '골라주세요', '찾아주세요', '알려주세요', '보여주세요',
            '되어도', '되어서', '이어도', '있어도', '없어도',
            '원단으로', '소파를', '소파가', '소파에', '소파로',
        }

        # 2글자 이상 한글 추출
        words = _re.findall(r'[가-힣]{2,}', direct_input)
        _seen_clean = set()  # 중복 방지!

        for word in words:
            # 불용어 제거
            if word in STOPWORDS:
                continue
            # 조사/어미 제거
            clean = _re.sub(JOSA_PATTERN, '', word)
            # 중복/불용어/2글자 미만 제거
            if len(clean) >= 2 and clean not in STOPWORDS and clean not in _seen_clean:
                _seen_clean.add(clean)
                match_keywords.append(clean)

    # 중복 제거
    match_keywords = list(dict.fromkeys(match_keywords))
    return match_keywords


def filter_genuine_reviews(all_reviews: list) -> tuple:
    """
    광고 제거 + 진짜 후기 판별
    → recommendation.py에서 분리!
    → 센서 키워드로 광고/진짜/의심 분류

    반환: (genuine_reviews, ad_count, suspect_count)
    """
    genuine_reviews = []
    ad_count = 0
    suspect_count = 0

    for r in all_reviews:
        text = r if isinstance(r, str) else r.get('text', '')
        title = r.get('title', text[:30]) if isinstance(r, dict) else text[:30]

        # ★ 광고 필터 - 어떤 패턴에 걸렸는지 로그!
        matched_pattern = next(
            (ex for ex in EXCLUDE_PATTERNS if ex in text), None
        )
        if matched_pattern:
            ad_count += 1
            print(f'[광고감지] "{matched_pattern}" → {title[:30]}')
            continue

        # ★ 진짜 후기 판별 - 어떤 센서 키워드로 통과했는지 로그!
        matched_axis = None
        for axis, kws in GENUINE_REVIEW_KEYWORDS.items():
            if any(kw in text for kw in kws):
                matched_axis = axis
                break

        if matched_axis:
            genuine_reviews.insert(0, r)
            print(f'[진짜후기] {matched_axis} → {title[:30]}')
        else:
            # 키워드 없는 후기 → 의심!
            suspect_count += 1
            genuine_reviews.append(r)
            if suspect_count <= 3:
                print(f'[의심후기] 키워드없음 → {title[:30]}')

    print(f'[광고제거] {ad_count}개 제거 / 진짜={len(genuine_reviews) - suspect_count}개 / 의심={suspect_count}개')
    return genuine_reviews, ad_count, suspect_count


def extract_direct_keywords(direct_input: str) -> list:
    """
    직접입력에서 핵심 명사 추출
    LLM 변환 없이 코드로 일관되게!
    → 깔끔한 입력도, 개판 입력도 핵심만 살아남음!

    예:
    "양방향 입체기울기로 책이 떨어지지 않는 아기 독서대"
    → ['양방향', '입체기울기', '아기', '독서대']

    "아 몰라 그거 양방향 이짜라요 아니 뭐더라"
    → ['양방향', '입체']
    """
    if not direct_input:
        return []

    import re as _re

    # 2글자 이상 한글/영문 추출
    words = _re.findall(r'[가-힣a-zA-Z]{2,}', direct_input)

    # 불용어 (검색에 의미없는 단어들)
    STOPWORDS = {
        # 요청 표현
        '있어요', '없어요', '골라줘요', '찾아줘요', '해주세요', '싶어요',
        '찾아줘', '골라줘', '해줘', '주세요', '알려줘', '보여줘',
        # 모호한 표현
        '그거', '몰라', '아니', '뭐더라', '이짜라요', '그런데', '그리고',
        '아무튼', '아무거나', '뭐든', '어떤', '좋은', '좋아요',
        # 조사성 표현
        '있는', '없는', '되는', '하는', '이런', '저런', '그런',
        # 불필요 명사
        '것이', '것을', '정도', '진짜', '그냥', '완전',
        # 부정 표현 (검색에 방해)
        '않는', '않고', '묻지', '떨어지지', '밀리지', '빠지지',
        # 일반 명사 (너무 광범위)
        '제품', '책이', '아이가',
    }

    # 조사 제거 패턴
    JOSA = r'(이|가|을|를|은|는|로|으로|에|의|와|과|도|만)$'

    result = []
    seen = set()
    for word in words:
        if word in STOPWORDS:
            continue
        clean = _re.sub(JOSA, '', word, 1)
        if len(clean) >= 2 and clean not in STOPWORDS and clean not in seen:
            seen.add(clean)
            result.append(clean)

    return result[:4]  # 최대 4개


# ============================================
# ★ 새 카드 구조 - 이 제품의 특징 + 비추천 조건
# 동현님 설계 / 로드 구현 2026-05-16
# ============================================

def build_product_features(reviews: list, product_name: str, call_llm_fn=None, direct_input: str = '') -> list:
    """
    리뷰에서 제품 특징 추출 + 직접입력 맥락 반영
    목/허리 아픔 → 헤드틸팅 앞으로 + "목이 아프시죠?"
    강아지 → 패브릭/세탁 앞으로 + "강아지 있으시죠?"
    아이 → 이지클린/안전 앞으로 + "아이 있으시죠?"
    """
    if not reviews or not call_llm_fn:
        return []

    review_texts = '\n'.join([f'- {r["text"][:150]}' for r in reviews[:30]])

    # 직접입력 맥락 분석
    context_hint = ''
    if direct_input:
        _di = direct_input
        _has_neck    = any(k in _di for k in ['목', '허리', '등', '통증', '아파', '불편'])
        _has_pet     = any(k in _di for k in ['강아지', '고양이', '반려', '펫', '애견', '애묘'])
        _has_kid     = any(k in _di for k in ['아이', '아기', '어린이', '유아', '아들', '딸', '육아'])
        _has_narrow  = any(k in _di for k in ['좁은', '소형', '작은', '협소'])

        hints = []
        if _has_neck:   hints.append('목/허리가 불편한 분 → 헤드틸팅·리클라이너·등받이 조절 특징 앞으로')
        if _has_pet:    hints.append('반려동물 있는 집 → 패브릭 소재·세탁·청소 특징 앞으로')
        if _has_kid:    hints.append('아이 있는 집 → 이지클린·방수·안전 특징 앞으로')
        if _has_narrow: hints.append('좁은 공간 → 컴팩트·공간활용 특징 앞으로')

        if hints:
            context_hint = ' / '.join(hints)

    context_section = f'''

사용자 상황: {context_hint}
→ 위 상황에 맞는 특징을 맨 앞에 배치하세요.
→ 해당 특징 설명에서 사용자 상황과 직접 관련된 핵심 단어 1~2개만 __밑줄__(예: __목을 편하게__, __물이 스며들지 않아__)로 강조하세요.
→ 관련 없는 단어나 전체 문장에는 절대 밑줄 금지.
→ 같은 표현을 카드마다 반복하지 말고 자연스럽게 다르게 표현하세요.
→ ** 별표 볼드 표시는 절대 사용 금지.''' if context_hint else ''

    prompt = f"""{product_name} 실제 사용자 후기들이에요:
{review_texts}

이 제품의 핵심 특징 3~5개를 뽑아주세요.{context_section}

형식 (각 특징마다):
특징명 (한 줄 태그): 구체적인 설명 1~2문장

규칙:
- 특징명 옆 괄호 안에 이 특징이 누구에게 좋은지 5~10자로 태그 달기
  예: (목 아픈 분께), (강아지 있는 집), (아이 있는 집), (좁은 거실에)
- 사용자 맥락과 관련 없는 특징은 괄호 태그 생략
- 후기에 구체적인 설명이 있으면 그 내용을 다듬어서 써주세요
- 전문용어는 반드시 풀어서 설명
- 광고 느낌 금지, 솔직하게
- 한 줄에 하나, 불릿/번호 없이

좋은 예:
헤드틸팅 기능 (목 아프신 분께): 소파 헤드 부분이 위로 젖혀져 __목을 편하게__ 받쳐줘요.
아쿠아텍스 원단 (강아지·아이 있는 집): 물이 스며들지 않아 물티슈로 바로 닦여요.
직선형 디자인: 어떤 거실에도 잘 어울리는 심플한 라인이에요."""

    try:
        result = call_llm_fn(prompt, max_tokens=600).strip()
        features = [line.strip() for line in result.split('\n') if line.strip() and len(line.strip()) >= 6]
        features = [f for f in features if not any(x in f for x in ['규칙', '예시', '출력', '금지', '형식', '좋은 예'])]
        # # 마크다운 제목 필터링
        features = [f for f in features if not f.startswith('#')]
        print(f'[제품특징] {len(features)}개 추출 (맥락: {context_hint[:20] if context_hint else "없음"})')
        return features[:5]
    except Exception as e:
        print(f'[제품특징오류] {e}')
        return []


def build_fit_or_not(reviews: list, product_name: str, selections: str, call_llm_fn=None) -> dict:
    """
    이런 분께 맞아요 + 이런 분께 아닌 분 + 픽코 한줄평
    기존 situations + one_line 합침
    """
    if not reviews or not call_llm_fn:
        return {'fit': [], 'not_fit': [], 'one_line': ''}

    review_texts = '\n'.join([f'- {r["text"][:100]}' for r in reviews[:20]])

    prompt = f"""{product_name} 실제 사용자 후기들이에요:
{review_texts}

아래 형식으로만 출력하세요. 다른 말 금지.

[맞아요]
소형 평수 거주자
좁은 거실 활용자

[아닌 분]
4인 이상 가족
장시간 앉는 분

[한줄평]
좁은 거실에 딱 맞는 컴팩트 소파예요

위 예시처럼 실제 이 제품({product_name}) 후기를 바탕으로 작성하세요.
맞아요 2개, 아닌 분 2개, 한줄평 1개만."""

    try:
        result = call_llm_fn(prompt, max_tokens=200).strip()

        fit, not_fit, one_line = [], [], ''
        current = None
        for line in result.split('\n'):
            line = line.strip()
            if '[맞아요]' in line:
                current = 'fit'
            elif '[아닌 분]' in line:
                current = 'not_fit'
            elif '[한줄평]' in line:
                current = 'one_line'
            elif line and current == 'fit':
                fit.append(line)
            elif line and current == 'not_fit':
                not_fit.append(line)
            elif line and current == 'one_line':
                one_line = line

        print(f'[맞아요/아닌분] 맞아요={len(fit)}개 아닌분={len(not_fit)}개')
        return {'fit': fit[:3], 'not_fit': not_fit[:2], 'one_line': one_line}
    except Exception as e:
        print(f'[맞아요/아닌분오류] {e}')
        return {'fit': [], 'not_fit': [], 'one_line': ''}


def build_picko_critique(products: list, user_context: str, call_llm_fn=None) -> list:
    """
    픽코 총평 - 각 카드마다 비평 하나씩 (총 3개)
    1순위: 자체 평가 + 2,3순위 대비 약점
    2순위: 1순위 대비 차별점
    3순위: 세 개 중 솔직한 결론
    """
    if not products or not call_llm_fn:
        return ''

    # 3개 제품 데이터 정리
    prod_summaries = []
    for i, p in enumerate(products[:3]):
        name = p.get('name', '')[:20]
        price = p.get('price', '')
        pros = p.get('pros', [])
        cons = p.get('cons', [])
        sensor = p.get('sensor_tag', '')
        ratings = p.get('picko_ratings', [])
        quality = next((r.get('pct', 0) for r in ratings if '품질' in r.get('label', '')), 0)
        prod_summaries.append(
            f"{i+1}순위: {name} / {price}원 / 품질{quality}% / {sensor} / "
            f"장점:{','.join(pros[:2])} / 단점:{','.join(cons[:2])}"
        )

    prods_text = '\n'.join(prod_summaries)

    prompts = [
        f"""픽코예요. 3개 소파 추천했어요.
사용자: {user_context}
제품: {prods_text}

1순위 비평을 써주세요.
형식: 3문장, 줄바꿈 없이 한 문단
구조: ①자체평가(이래서 추천) ②2순위 대비 비싼 이유 ③결론
예시: 기능은 확실히 잡았어요. 헤드틸팅에 아쿠아텍스까지 이 가격대에 이 조합 찾기 쉽지 않아요. 근데 2순위보다 20만원 더 비싼데 그 차이는 브랜드 신뢰도와 마감에서 나와요.
규칙: 광고 금지, 사람 말투, 3문장 딱 맞게""",

        f"""픽코예요. 3개 소파 추천했어요.
사용자: {user_context}
제품: {prods_text}

2순위 비평을 써주세요.
형식: 3문장, 줄바꿈 없이 한 문단
구조: ①자체평가(이래서 추천) ②1순위 대비 가격 차이 ③결론
규칙: 광고 금지, 사람 말투, 3문장 딱 맞게""",

        f"""픽코예요. 3개 소파 추천했어요.
사용자: {user_context}
제품: {prods_text}

3순위 비평을 써주세요.
형식: 3문장, 줄바꿈 없이 한 문단
구조: ①자체평가(이래서 추천) ②1·2순위 대비 솔직하게 ③결론(살 이유 있으면 짧게)
규칙: 광고 금지, 사람 말투, 독하게, 3문장 딱 맞게"""
    ]

    prompt = prompts[0]  # 임시 (아래에서 3개 각각 생성)

    try:
        critiques = []
        for i, p in enumerate(prompts):
            r = call_llm_fn(p, max_tokens=250).strip()
            print(f'[총평비평] {i+1}순위 {len(r)}자 생성')
            critiques.append(r)
        return critiques
    except Exception as e:
        print(f'[총평비평오류] {e}')
        return []
