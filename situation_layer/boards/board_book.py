# 책 상황판
# 2구역 1단계: 장르
# 어린이: 2단계 (형태 → 종류)

BOOK_GENRES = ['소설', '자기계발', '경제경영', '에세이', '과학', '역사', '어린이', '만화']

BOOK_BOARDS = {
    '소설': [
        ('국내해외', ['국내', '해외번역']),
        ('장르', ['로맨스', '추리/미스터리', 'SF/판타지', '역사소설', '공포/스릴러', '상관없음']),
        ('두께', ['단편', '중편', '장편']),
        ('가격', ['1만원이하', '1~2만원', '2만원이상']),
        ('직접입력', []),
    ],
    '자기계발': [
        ('분야', ['성공', '습관', '심리', '리더십']),
        ('두께', ['얇은', '보통', '두꺼운']),
        ('가격', ['1만원이하', '1~2만원', '2만원이상']),
        ('직접입력', []),
    ],
    '경제경영': [
        ('분야', ['투자', '창업', '마케팅', '경제이론']),
        ('두께', ['얇은', '보통', '두꺼운']),
        ('가격', ['1만원이하', '1~2만원', '2만원이상']),
        ('직접입력', []),
    ],

    '어린이_단행본': [
        ('연령', ['0~3세', '4~7세', '8~13세']),
        ('장르', ['그림책', '동화', '학습', '과학']),
        ('언어', ['한국어', '영어', '기타']),
        ('가격', ['1만원이하', '1~2만원', '2만원이상']),
        ('직접입력', []),
    ],
    '어린이_세트': [
        ('연령', ['0~3세', '4~7세', '8~13세']),
        ('장르', ['창작동화', '세계명작', '학습만화', '과학']),
        ('권수', ['10권이하', '10~30권', '30권이상']),
        ('가격', ['10만원이하', '10~30만원', '30만원이상']),
        ('직접입력', []),
    ],
}

CHILDREN_FORMS = ['단행본', '세트·전집']
CHILDREN_TYPES = ['팝업북', '사운드북', '보드북', '수입원서', '일반']


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    # 아동/유아/아기 → 어린이로 통합
    if context in ['아동', '유아', '아기', '키즈']:
        context = '어린이'
    # 어린이 2단계
    if context == '어린이':
        return 'CONTEXT_SELECT:' + '/'.join(CHILDREN_FORMS)
    if context in CHILDREN_FORMS:
        return 'CONTEXT_SELECT:' + '/'.join(CHILDREN_TYPES)
    if context in CHILDREN_TYPES:
        key = f'어린이_{choice}' if choice else '어린이_단행본'
        return render_board(BOOK_BOARDS.get(key, BOOK_BOARDS['어린이_단행본']))
    # 일반 장르
    if context and context in BOOK_BOARDS:
        return render_board(BOOK_BOARDS[context])
    # 없는 장르 → LLM 폴백
    if context and context in BOOK_GENRES:
        from .board_llm import get_board as llm_b
        return llm_b(product=f'{context} 책')
    return 'CONTEXT_SELECT:' + '/'.join(BOOK_GENRES)
