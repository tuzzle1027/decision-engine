# 수영복 상황판
# 2구역 1단계: 남성/여성/아동
# 2구역 2단계: 종류
# 3구역: 상황판

SWIMWEAR_TYPES = {
    '남성': ['트렁크', '보드숏', 'jammers', '래쉬가드'],
    '여성': ['원피스', '비키니', '래쉬가드', '탱키니'],
    '아동': ['원피스', '래쉬가드', '비키니'],
}

SWIMWEAR_BOARDS = {
    '레저': [
        ('용도', ['일반', '비치']),
        ('브랜드', ['스피도', '아레나', '나이키', '상관없음']),
        ('가격', ['3만원이하', '3~10만원', '10만원이상']),
        ('직접입력', []),
    ],
    '선수용': [
        ('용도', ['준선수', '선수용']),
        ('브랜드', ['스피도', '아레나', '상관없음']),
        ('가격', ['5만원이하', '5~15만원', '15만원이상']),
        ('직접입력', []),
    ],
}

SWIMWEAR_GENDER = ['남성', '여성', '아동']


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    # 성별 선택
    if context in SWIMWEAR_TYPES:
        types = SWIMWEAR_TYPES[context]
        return 'CONTEXT_SELECT:' + '/'.join(types)
    # 종류 선택 후 상황판
    if context in ['jammers']:
        return render_board(SWIMWEAR_BOARDS['선수용'])
    if context in ['트렁크', '보드숏', '래쉬가드', '원피스', '비키니', '탱키니']:
        return render_board(SWIMWEAR_BOARDS['레저'])
    # 기본 성별 선택
    return 'CONTEXT_SELECT:' + '/'.join(SWIMWEAR_GENDER)
