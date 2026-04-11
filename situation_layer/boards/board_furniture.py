# board_furniture.py
# 가구 / 인테리어 카테고리 상황판
# 2구역 → 2-1구역 → 3구역

# ─────────────────────────────────────────
# 2구역 매핑
# ─────────────────────────────────────────
FURNITURE_2ZONE = {
    '침대':       ['싱글', '슈퍼싱글', '퀸', '킹', '패밀리'],
    '매트리스':   ['스프링', '포켓스프링', '메모리폼', '라텍스'],
    '소파':       ['1인용', '2인용', '3인용', '4인용', '6인용이상', '리클라이너'],
    '책상':       ['사무용', '학생용', '게이밍'],
    '의자':       ['사무용', '게이밍', '식탁의자', '바체어', '접이식', '기능형', '스툴'],
    '식탁':       ['원목', '대리석', '세라믹'],
    '수납가구':   ['옷장', '붙박이장', '서랍장', '책장', '선반', '수납장', 'TV장', '거실장', '신발장', '화장대'],
    '커튼':       ['암막커튼', '쉬폰커튼', '린넨커튼', '롤스크린', '우드블라인드', '콤비블라인드', '버티컬블라인드'],
    '블라인드':   ['롤스크린', '우드블라인드', '콤비블라인드', '버티컬블라인드'],
    '러그':       None,  # 바로 3구역
    '카페트':     None,  # 바로 3구역
    '인테리어소품': ['액자', '탁상시계', '벽시계', '거울', '화분', '캔들', '디퓨저', '트레이', '쿠션', '조명'],
    '소품':          ['액자', '탁상시계', '벽시계', '거울', '화분', '캔들', '디퓨저', '트레이', '쿠션', '조명'],
    '조명':       ['스탠드', '무드등', '천장조명', '벽조명'],
}

# 소파 2-1구역 (소재)
SOFA_MATERIAL = ['가죽', '인조가죽', '패브릭', '기능성패브릭', '벨벳', '마이크로화이버']

# 책상 2-1구역 (형태)
DESK_TYPE = ['일반형', '높이조절', 'L자형', '스탠딩']

# ─────────────────────────────────────────
# ZONE_RULES: 카테고리별 구역 판단 공식
# 새 카테고리 추가 = 여기 한 줄만!
# ─────────────────────────────────────────
ZONE_RULES = {
    '소파':  {'context_key': '인원수', 'sub_key': '소재', 'sub_options': SOFA_MATERIAL,
              'context_normalize': {'6인용': '6인용이상'}},
    '쇼파':  {'context_key': '인원수', 'sub_key': '소재', 'sub_options': SOFA_MATERIAL,
              'context_normalize': {'6인용': '6인용이상'}},
    '침대':  {'context_key': '사이즈', 'sub_key': None, 'context_normalize': {}},
    '매트리스': {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    '책상':  {'context_key': '용도', 'sub_key': None,
              'context_normalize': {'학생용': '학생용_높이조절', '사무용': '사무용_일반형'}},
    '의자':  {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    '식탁':  {'context_key': '소재', 'sub_key': None, 'context_normalize': {}},
    '수납가구': {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    '커튼':  {'context_key': '종류', 'sub_key': None,
              'context_normalize': {'암막': '암막커튼', '린넨': '린넨커튼'}},
    '블라인드': {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    '러그':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '카페트': {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '인테리어소품': {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    '조명':  {'context_key': '종류', 'sub_key': None, 'context_normalize': {}},
    # 수납가구 하위 → context 불필요 → 바로 3구역 (보드 직행)
    '옷장':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '서랍장':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '책장':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '신발장':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '거실장':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '화장대':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '수납장':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    'TV장':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    # 소품 하위 → 바로 3구역
    '트레이':  {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '액자':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '거울':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '화분':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
    '쿠션':    {'context_key': None, 'sub_key': None, 'context_normalize': {}},
}


def get_all_options(product: str) -> dict:
    """제품의 모든 보드 옵션 추출 → normalize_query에 힌트로 전달"""
    all_options = {}
    prod = BOARD_ALIAS.get(product, product)
    for key, items in FURNITURE_BOARDS.items():
        if prod in key or key.startswith(prod):
            for label, options in items:
                if label == '직접입력' or not options:
                    continue
                if label not in all_options:
                    all_options[label] = set()
                all_options[label].update(options)
    # ZONE_RULES context_key + FURNITURE_2ZONE 옵션 포함
    rule = ZONE_RULES.get(product, {})
    context_key = rule.get('context_key')
    if context_key:
        # FURNITURE_2ZONE에서 2구역 선택지 가져오기
        zone_opts = FURNITURE_2ZONE.get(product, [])
        if zone_opts:
            if context_key not in all_options:
                all_options[context_key] = set()
            all_options[context_key].update(zone_opts)
    # sub_options 포함 (소재 등)
    if rule.get('sub_key') and rule.get('sub_options'):
        label = rule['sub_key']
        if label not in all_options:
            all_options[label] = set()
        all_options[label].update(rule['sub_options'])
    return {k: sorted(v) for k, v in all_options.items()}


def get_zone(product: str, selected: dict) -> str:
    """ZONE_RULES 기반 2/3구역 자동 판단. 새 카테고리 = ZONE_RULES 한 줄 추가!"""
    rule = ZONE_RULES.get(product)
    if not rule or not rule.get('context_key'):
        return '3'  # 러그/카페트 등 context 불필요 → 바로 3구역
    has_context = rule['context_key'] in selected
    has_sub = (rule['sub_key'] in selected) if rule.get('sub_key') else True
    return '3' if (has_context and has_sub) else '2'


def resolve_context(product: str, selected: dict, context: str = None, choice: str = None):
    """ZONE_RULES 기반 selected에서 context/choice 자동 추출"""
    rule = ZONE_RULES.get(product)
    if not rule:
        return context, choice
    context_key = rule.get('context_key')
    sub_key = rule.get('sub_key')
    normalize = rule.get('context_normalize', {})
    if not context and context_key and context_key in selected:
        context = normalize.get(selected[context_key], selected[context_key])
    if not choice and sub_key and sub_key in selected:
        choice = selected[sub_key]
    return context, choice

# ─────────────────────────────────────────
# 3구역 상황판
# ─────────────────────────────────────────
FURNITURE_BOARDS = {

    # ── 침대 ──
    '침대_싱글': [
        ('프레임높이', ['낮은형', '일반형', '높은형']),
        ('수납형태', ['서랍형', '리프트형', '오픈형', '없음']),
        ('헤드유무', ['헤드있음', '헤드없음']),
        ('매트리스', ['포함', '별도구매']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '침대_슈퍼싱글': [
        ('프레임높이', ['낮은형', '일반형', '높은형']),
        ('수납형태', ['서랍형', '리프트형', '오픈형', '없음']),
        ('헤드유무', ['헤드있음', '헤드없음']),
        ('헤드기능', ['수납형', '조명형', '기본형']),
        ('프레임색상', ['밝은톤', '중간톤', '어두운톤']),
        ('매트리스', ['포함', '별도구매']),
        ('매트리스종류', ['스프링', '포켓스프링', '메모리폼', '라텍스']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '침대_퀸': [
        ('프레임높이', ['낮은형', '일반형', '높은형']),
        ('수납형태', ['서랍형', '리프트형', '오픈형', '없음']),
        ('헤드유무', ['헤드있음', '헤드없음']),
        ('헤드기능', ['수납형', '조명형', '기본형']),
        ('매트리스', ['포함', '별도구매']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '침대_킹': [
        ('프레임높이', ['낮은형', '일반형', '높은형']),
        ('수납형태', ['서랍형', '리프트형', '오픈형', '없음']),
        ('헤드유무', ['헤드있음', '헤드없음']),
        ('헤드기능', ['수납형', '조명형', '기본형']),
        ('매트리스', ['포함', '별도구매']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '침대_패밀리': [
        ('구성', ['더블퀸', '킹+싱글', '맞춤형']),
        ('수납형태', ['서랍형', '리프트형', '없음']),
        ('매트리스', ['포함', '별도구매']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 매트리스 ──
    '매트리스_스프링': [
        ('쿠션감', ['푹신함', '적당함', '단단함']),
        ('두께', ['20cm', '25cm', '30cm이상']),
        ('커버세탁', ['가능', '불가능']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '매트리스_포켓스프링': [
        ('쿠션감', ['푹신함', '적당함', '단단함']),
        ('상단소재', ['폼', '메모리폼', '라텍스']),
        ('두께', ['20cm', '25cm', '30cm이상']),
        ('커버세탁', ['가능', '불가능']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '매트리스_메모리폼': [
        ('쿠션감', ['푹신함', '적당함', '단단함']),
        ('두께', ['얇음', '보통', '두꺼움']),
        ('커버세탁', ['가능', '불가능']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '매트리스_라텍스': [
        ('쿠션감', ['푹신함', '적당함', '단단함']),
        ('두께', ['얇음', '보통', '두꺼움']),
        ('소재', ['천연', '합성']),
        ('통기성', ['기본', '강화']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 소파 ──
    '소파_1인용_패브릭': [
        ('쿠션감', ['푹신함', '적당함', '단단함']),
        ('패브릭기능', ['기본', '방수', '오염방지', '스크래치방지']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '소파_3인용_패브릭': [
        ('형태', ['직선형', '코너형', '카우치형', '모듈형']),
        ('좌방석쿠션', ['푹신함', '적당함', '단단함']),
        ('패브릭기능', ['기본', '방수', '오염방지', '스크래치방지']),
        ('커버세탁', ['가능', '불가능']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '소파_6인용이상_패브릭': [
        ('형태', ['직선형', '코너형', '카우치형', '모듈형']),
        ('좌방석쿠션', ['푹신함', '적당함', '단단함']),
        ('패브릭기능', ['기본', '방수', '오염방지', '스크래치방지']),
        ('프레임', ['원목', '스틸', '혼합']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '소파_리클라이너': [
        ('작동방식', ['수동', '전동']),
        ('소재', ['가죽', '인조가죽', '패브릭']),
        ('기능', ['1단', '2단', '풀플랫']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 책상 ──
    '책상_사무용_일반형': [
        ('상판크기', ['120cm', '140cm', '160cm', '180cm']),
        ('프레임', ['스틸', '원목', '혼합']),
        ('상판재질', ['PB', 'MDF', 'LPM', '원목']),
        ('수납', ['있음', '없음']),
        ('케이블정리', ['있음', '없음']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '책상_학생용_높이조절': [
        ('상판각도조절', ['가능', '불가능']),
        ('높이조절방식', ['수동', '전동']),
        ('상판크기', ['100cm', '120cm', '140cm']),
        ('상판재질', ['MDF', 'PB', '원목']),
        ('수납', ['서랍형', '선반형', '없음']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '책상_게이밍': [
        ('상판크기', ['120cm', '140cm', '160cm']),
        ('형태', ['일반형', 'L자형']),
        ('모니터암홀', ['있음', '없음']),
        ('케이블정리', ['있음', '없음']),
        ('색상', ['블랙', '화이트', '기타']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 의자 ──
    '의자_사무용': [
        ('소재', ['메쉬', '패브릭', '가죽', '인조가죽']),
        ('좌방석쿠션', ['푹신함', '적당함', '단단함']),
        ('팔걸이', ['없음', '있음']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '의자_기능형': [
        ('소재', ['메쉬', '패브릭', '가죽', '인조가죽']),
        ('팔걸이', ['없음', '고정형', '조절형']),
        ('등받이조절', ['없음', '기본', '고급']),
        ('요추지지', ['없음', '기본', '조절형']),
        ('헤드레스트', ['없음', '있음']),
        ('바퀴', ['일반', '저소음', '고급']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '의자_게이밍': [
        ('소재', ['패브릭', '인조가죽', '가죽']),
        ('등받이각도', ['기본', '풀플랫']),
        ('팔걸이', ['고정형', '4D조절형']),
        ('색상', ['블랙', '블랙레드', '화이트', '기타']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '의자_스툴': [
        ('형태', ['원형', '사각형', '등받이형']),
        ('높이', ['낮음', '중간', '높음']),
        ('좌방석쿠션', ['없음', '얇음', '푹신함']),
        ('구조소재', ['원목', '스틸', '플라스틱', '혼합']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],

    # ── 식탁 ──
    '식탁_원목': [
        ('인원수', ['2인용', '4인용', '6인용']),
        ('형태', ['직사각형', '원형', '타원형', '확장형']),
        ('목재톤', ['밝은톤', '중간톤', '어두운톤']),
        ('마감', ['내추럴', '코팅', '오일마감']),
        ('프레임', ['원목', '스틸', '혼합']),
        ('의자구성', ['테이블만', '의자포함']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '식탁_대리석': [
        ('인원수', ['2인용', '4인용', '6인용']),
        ('형태', ['직사각형', '원형', '타원형', '확장형']),
        ('마감', ['유광', '무광']),
        ('프레임', ['스틸', '원목', '혼합']),
        ('의자구성', ['테이블만', '의자포함']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '식탁_세라믹': [
        ('인원수', ['2인용', '4인용', '6인용']),
        ('형태', ['직사각형', '원형', '확장형']),
        ('마감', ['유광', '무광']),
        ('프레임', ['스틸', '원목', '혼합']),
        ('의자구성', ['테이블만', '의자포함']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 수납가구 ──
    '수납가구_옷장': [
        ('형태', ['일반형', '붙박이형']),
        ('문방식', ['여닫이', '슬라이딩', '오픈형']),
        ('폭', ['800', '1200', '1600', '1800', '2000', '2400']),
        ('높이', ['1800', '2000', '2100', '2400']),
        ('소재', ['파티클보드', 'MDF', '원목', '스틸']),
        ('내부구성', ['행거형', '선반형', '혼합형']),
        ('거울', ['없음', '있음']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '수납가구_서랍장': [
        ('단수', ['3단', '4단', '5단']),
        ('폭', ['600', '800', '1000', '1200']),
        ('소재', ['플라스틱', 'MDF', '원목', '혼합']),
        ('손잡이', ['없음', '매립형', '돌출형']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '수납가구_책장': [
        ('높이', ['1200', '1500', '1800', '2000']),
        ('폭', ['600', '800', '1000', '1200']),
        ('선반조절', ['가능', '불가능']),
        ('소재', ['MDF', 'PB', '원목', '혼합']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],
    '수납가구_화장대': [
        ('폭', ['600', '800', '1000', '1200']),
        ('거울', ['없음', '있음', '접이식']),
        ('수납', ['서랍형', '선반형', '혼합형']),
        ('조명', ['없음', '기본', 'LED조명']),
        ('의자포함', ['없음', '포함']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 인테리어 소품 ──
    '소품_트레이': [
        ('크기', ['소형', '중형', '대형']),
        ('용도', ['식탁용', '주방정리용', '욕실용', '다목적용']),
        ('소재', ['플라스틱', '스테인리스', '우드', '메탈']),
        ('색상', ['블랙', '화이트', '그레이', '우드톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_트레이': [
        ('크기', ['소형', '중형', '대형']),
        ('용도', ['식탁용', '주방정리용', '욕실용', '다목적용']),
        ('소재', ['플라스틱', '스테인리스', '우드', '메탈']),
        ('색상', ['블랙', '화이트', '그레이', '우드톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_액자': [
        ('프레임', ['원목', '메탈', '플라스틱']),
        ('설치방식', ['벽걸이', '거치형', '겸용']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_거울': [
        ('형태', ['전신거울', '벽거울', '탁상거울']),
        ('프레임', ['원목', '메탈', '플라스틱', '무프레임']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_화분': [
        ('크기', ['소형', '중형', '대형']),
        ('소재', ['플라스틱', '세라믹', '테라코타']),
        ('배수', ['구멍있음', '없음']),
        ('형태', ['원형', '사각형', '긴형']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_캔들': [
        ('향기', ['무향', '플로럴', '시트러스', '달콤', '우디', '허브', '프레쉬']),
        ('용기타입', ['유리', '틴캔', '세라믹', '기둥형']),
        ('크기', ['소형', '중형', '대형']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_디퓨저': [
        ('향기', ['무향', '플로럴', '시트러스', '달콤', '우디', '허브', '프레쉬']),
        ('용기타입', ['유리', '세라믹', '플라스틱']),
        ('용량', ['100ml', '200ml', '500ml이상']),
        ('스틱', ['기본', '우드스틱', '섬유스틱']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_쿠션': [
        ('크기', ['30x30', '40x40', '45x45', '50x50', '60x60']),
        ('충전재', ['솜', '메모리폼', '마이크로화이버', '구스']),
        ('커버소재', ['패브릭', '린넨', '벨벳', '가죽']),
        ('세탁', ['가능', '불가능']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_조명_스탠드': [
        ('형태', ['탁상형', '플로어형']),
        ('빛색', ['주광색', '주백색', '전구색']),
        ('밝기조절', ['가능', '불가능']),
        ('전원', ['콘센트', 'USB']),
        ('색상', ['화이트', '블랙', '실버', '기타']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '소품_조명_무드등': [
        ('형태', ['구형', '원통형', '오브제형']),
        ('빛색', ['주광색', '주백색', '전구색']),
        ('소재', ['유리', '패브릭', '우드', '세라믹']),
        ('전원', ['배터리', '충전식', 'USB']),
        ('기능', ['터치', '리모컨', '타이머']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],

    # ── 커튼/블라인드 ──
    '커튼_암막': [
        ('차광률', ['70%', '90%', '100%']),
        ('두께', ['얇음', '보통', '두꺼움']),
        ('설치방식', ['봉형', '레일형']),
        ('주름형태', ['없음(플랫)', '일반주름', '나비주름']),
        ('사이즈', ['100', '150', '200', '맞춤']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
    '커튼_린넨': [
        ('투명도', ['비침', '반투명', '불투명']),
        ('설치방식', ['봉형', '레일형']),
        ('주름형태', ['없음(플랫)', '일반주름', '나비주름']),
        ('사이즈', ['100', '150', '200', '맞춤']),
        ('색상', ['밝은톤', '내추럴톤', '중간톤']),
        ('가격', ['저가', '중가', '고가', '프리미엄']),
        ('직접입력', []),
    ],

    # ── 러그/카페트 ──
    '러그': [
        ('형태', ['사각형', '원형', '타원형']),
        ('질감', ['장모', '단모']),
        ('크기', ['소형', '중형', '대형']),
        ('색상', ['밝은톤', '중간톤', '어두운톤']),
        ('가격', ['저가', '중가', '고가']),
        ('직접입력', []),
    ],
}

# 별칭 매핑
BOARD_ALIAS = {
    '카페트': '러그',
    '블라인드': '커튼_암막',
    '트레이': '소품_트레이',
}

# ─────────────────────────────────────────
# 렌더링
# ─────────────────────────────────────────
def render_board(items, skip_labels=None, pre_selected=None):
    """상황판 렌더링. pre_selected에 있는 항목은 미리 체크 표시"""
    skip_labels = skip_labels or []
    pre_selected = pre_selected or {}
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            clean_options = [o.strip() for o in options if o.strip()]
            if label in pre_selected:
                checked_val = pre_selected[label].strip()
                lines.append(f'\n[{label}]\n' + ' / '.join(clean_options) + f' CHECKED:{checked_val}')
            else:
                lines.append(f'\n[{label}]\n' + ' / '.join(clean_options))
    return '\n'.join(lines)


# ─────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────
def get_board(product: str = '', context: str = None, choice=None) -> str:
    # choice가 dict면 selected_conditions (이미 선택된 조건)
    skip_labels = []
    selected = {}
    if isinstance(choice, dict):
        selected = choice
        choice = None
        # LLM이 이미 정확한 항목명으로 추출하므로 그대로 사용
        # 삭제 대신 미리 체크 표시로 보여줌
        skip_labels = []  # 더 이상 삭제 안 함

        # selected에서 context + choice 자동 추출 (context 있어도 choice 없으면 추출)
        context, choice = resolve_context(product, selected, context, choice)
        # ZONE_RULES에 없는 제품은 context 없이 진행 (보드 직접 찾기)
    """
    가구/인테리어 상황판 반환
    product: 대분류 (침대, 소파, 책상...)
    context: 2구역 선택값 (퀸, 3인용, 패브릭...)
    choice: 2-1구역 선택값 (소재 등)
    """

    # 별칭 처리
    if product in BOARD_ALIAS:
        product = BOARD_ALIAS[product]
    if context in BOARD_ALIAS:
        context = BOARD_ALIAS[context]

    # context 정규화 (암막커튼→암막)
    CTX_NORMALIZE = {
        '암막커튼': '암막', '린넨커튼': '린넨', '쉬폰커튼': '쉬폰',
        '수납장': '수납가구', '붙박이장': '옷장',
    }
    if context in CTX_NORMALIZE:
        context = CTX_NORMALIZE[context]
    
    # product 정규화
    PROD_NORMALIZE = {
        '책장': '수납가구', '서랍장': '수납가구', '화장대': '수납가구',
        '옷장': '수납가구', '거실장': '수납가구', '신발장': '수납가구',
        '스탠드': '조명', '무드등': '조명',
    }
    
    orig_product = product
    
    # 소품 직접 상황판 (2구역 스킵)
    DIRECT_SOFA_MAP = {
        '액자': '소품_액자', '거울': '소품_거울', '화분': '소품_화분', '트레이': '소품_트레이',
        '캔들': '소품_캔들', '디퓨저': '소품_디퓨저', '쿠션': '소품_쿠션',
        '트레이': '소품_트레이', '탁상시계': '소품_액자', '벽시계': '소품_액자',
        '조명': '소품_조명_스탠드',
    }
    if orig_product in DIRECT_SOFA_MAP:
        key = DIRECT_SOFA_MAP[orig_product]
        if key in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[key], skip_labels=skip_labels, pre_selected=selected)
    if product in PROD_NORMALIZE:
        product = PROD_NORMALIZE[product]

    # 러그/카페트 → 바로 3구역
    if product in ['러그', '카페트']:
        return render_board(FURNITURE_BOARDS['러그'], skip_labels=skip_labels, pre_selected=selected)

    # 슈퍼싱글 등 침대 사이즈가 product로 들어오는 경우
    BED_SIZE_MAP = {
        '슈퍼싱글': '침대_슈퍼싱글', '슈퍼싱글침대': '침대_슈퍼싱글',
        '퀸': '침대_퀸', '퀸침대': '침대_퀸',
        '킹': '침대_킹', '킹침대': '침대_킹',
        '싱글침대': '침대_싱글',
    }
    if orig_product in BED_SIZE_MAP:
        return render_board(FURNITURE_BOARDS[BED_SIZE_MAP[orig_product]], skip_labels=skip_labels, pre_selected=selected)

    # ── context가 재질/용도인 경우 바로 3구역 직행 ──
    DIRECT_CONTEXT = {
        # 식탁
        '원목': '식탁_원목', '대리석': '식탁_대리석', '세라믹': '식탁_세라믹',
        # 책상
        '학생용': '책상_학생용_높이조절', '사무용': '책상_사무용_일반형', '게이밍': '책상_게이밍',
        # 커튼
        '암막커튼': '커튼_암막', '암막': '커튼_암막',
        '린넨커튼': '커튼_린넨', '린넨': '커튼_린넨',
        # 침대 사이즈 직행
        '슈퍼싱글': '침대_슈퍼싱글', '퀸': '침대_퀸', '킹': '침대_킹', '싱글': '침대_싱글',
        # 소파 소재 직행 (인원수 스킵)
        '패브릭': '소파_3인용_패브릭', '가죽': '소파_3인용_패브릭',
    }
    if context in DIRECT_CONTEXT:
        key = DIRECT_CONTEXT[context]
        if key in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[key], skip_labels=skip_labels, pre_selected=selected)

    # context가 product와 같으면 무시
    if context == product or context == orig_product:
        context = None

    # 인테리어소품 → 2구역
    if product in ['인테리어소품', '소품'] and not context:
        options = FURNITURE_2ZONE.get('인테리어소품', [])
        return 'CONTEXT_SELECT:' + '/'.join(options)

    # ── 2구역: 대분류만 입력 ──
    if not context:
        # 수납가구 세부 아이템 직접 상황판
        direct_board_key = f'수납가구_{orig_product}'
        if direct_board_key in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[direct_board_key], skip_labels=skip_labels, pre_selected=selected)
        # 소품 세부 아이템
        direct_board_key2 = f'소품_{orig_product}'
        if direct_board_key2 in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[direct_board_key2], skip_labels=skip_labels, pre_selected=selected)
        options = FURNITURE_2ZONE.get(product)
        if options:
            return 'CONTEXT_SELECT:' + '/'.join(options)
        # LLM 폴백
        from .board_llm import get_board as llm_b
        return llm_b(product=orig_product)

    # ── 2-1구역 또는 3구역 ──
    # 소파: 인원수 선택 후 소재 선택 필요
    if product == '소파' and context in ['1인용','2인용','3인용','4인용','6인용이상']:
        if not choice:
            return 'CONTEXT_SELECT:' + '/'.join(SOFA_MATERIAL)
        # 소파 + 인원 + 소재 → 3구역
        key = f'소파_{context}_{choice}'
        if key in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[key], skip_labels=skip_labels, pre_selected=selected)
        # 없으면 가장 가까운 것
        key2 = f'소파_{context}_패브릭'
        if key2 in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[key2], skip_labels=skip_labels, pre_selected=selected)
        return render_board(FURNITURE_BOARDS['소파_3인용_패브릭'], skip_labels=skip_labels, pre_selected=selected)

    # 책상: 용도 선택 후 형태 선택 필요
    if product == '책상' and context in ['사무용','학생용','게이밍']:
        if context == '게이밍':
            return render_board(FURNITURE_BOARDS['책상_게이밍'], skip_labels=skip_labels, pre_selected=selected)
        if not choice:
            return 'CONTEXT_SELECT:' + '/'.join(DESK_TYPE)
        key = f'책상_{context}_{choice}'
        if key in FURNITURE_BOARDS:
            return render_board(FURNITURE_BOARDS[key], skip_labels=skip_labels, pre_selected=selected)
        # 폴백
        from .board_llm import get_board as llm_b
        return llm_b(product=f'{context} {context} 책상 {choice}형')

    # 일반 조합: product_context
    key = f'{product}_{context}'
    if key in FURNITURE_BOARDS:
        return render_board(FURNITURE_BOARDS[key], skip_labels=skip_labels, pre_selected=selected)

    # context만으로도 찾기
    if context in FURNITURE_BOARDS:
        return render_board(FURNITURE_BOARDS[context], skip_labels=skip_labels, pre_selected=selected)

    # LLM 폴백
    from .board_llm import get_board as llm_b
    return llm_b(product=f'{product} {context}')
