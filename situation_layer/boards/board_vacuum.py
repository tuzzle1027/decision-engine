# 청소기 상황판

VACUUM_BOARDS = {
    '가정_로봇청소기': [
        ('기능', ['청소만', '청소+물걸레', '자동비움']),
        ('공간', ['20평이하', '20~40평', '40평이상']),
        ('장애물', ['기본', '장애물감지', '카펫감지']),
        ('소음', ['조용한', '보통', '상관없음']),
        ('브랜드', ['삼성', 'LG', '로보락', '다이슨', '상관없음']),
        ('가격', ['20만원이하', '20~50만원', '50만원이상']),
        ('직접입력', []),
    ],
    '가정_무선': [
        ('흡입력', ['기본', '강력', '최강']),
        ('배터리', ['30분이하', '30~60분', '60분이상']),
        ('무게', ['가벼운', '보통', '상관없음']),
        ('브랜드', ['다이슨', '삼성', 'LG', '상관없음']),
        ('가격', ['15만원이하', '15~40만원', '40만원이상']),
        ('직접입력', []),
    ],
    '가정_유선': [
        ('흡입력', ['기본', '강력', '최강']),
        ('소음', ['조용한', '보통', '상관없음']),
        ('브랜드', ['삼성', 'LG', '다이슨', '상관없음']),
        ('가격', ['10만원이하', '10~30만원', '30만원이상']),
        ('직접입력', []),
    ],
    '가정_스팀': [
        ('용도', ['바닥전용', '다목적', '핸디형']),
        ('가열시간', ['빠른', '보통', '상관없음']),
        ('브랜드', ['카처', '테팔', '상관없음']),
        ('가격', ['10만원이하', '10~30만원', '30만원이상']),
        ('직접입력', []),
    ],
}

VACUUM_HOME_CONTEXTS = ['로봇청소기', '무선청소기', '유선청소기', '스팀청소기']
VACUUM_CONTEXTS = ['가정용', '업소용']


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    if context == '가정용':
        return 'CONTEXT_SELECT:' + '/'.join(VACUUM_HOME_CONTEXTS)
    key = f'가정_{context}' if context else None
    if key and key in VACUUM_BOARDS:
        return render_board(VACUUM_BOARDS[key])
    # 없는 context → LLM 폴백
    if context and context not in ['가정용', '업소용'] and context not in VACUUM_HOME_CONTEXTS:
        from .board_llm import get_board as llm_b
        return llm_b(product=f'{context} 청소기')
    return 'CONTEXT_SELECT:' + '/'.join(VACUUM_CONTEXTS)
