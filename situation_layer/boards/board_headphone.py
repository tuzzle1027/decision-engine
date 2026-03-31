# 헤드폰 상황판

HEADPHONE_BOARDS = {
    '오버이어': [
        ('연결', ['유선', '무선(블루투스)']),
        ('기능', ['일반', '노이즈캔슬링', '공간음향']),
        ('용도', ['음악감상', '게임', '통화', '운동']),
        ('브랜드', ['소니', '보스', '애플', '삼성', '상관없음']),
        ('가격', ['10만원이하', '10~30만원', '30만원이상']),
        ('직접입력', []),
    ],
    '인이어': [
        ('연결', ['유선', '무선(TWS)']),
        ('기능', ['일반', '노이즈캔슬링', '오픈이어']),
        ('용도', ['음악감상', '운동', '통화', '게임']),
        ('브랜드', ['애플', '삼성', '소니', '상관없음']),
        ('가격', ['5만원이하', '5~20만원', '20만원이상']),
        ('직접입력', []),
    ],
    '헤드셋': [
        ('연결', ['유선', '무선']),
        ('마이크', ['내장', '분리형']),
        ('호환', ['PC', '콘솔', '멀티']),
        ('브랜드', ['로지텍', '레이저', '젠하이저', '상관없음']),
        ('가격', ['5만원이하', '5~20만원', '20만원이상']),
        ('직접입력', []),
    ],
}

HEADPHONE_CONTEXTS = ['오버이어', '온이어', '인이어', '오픈이어', '헤드셋(게이밍)']


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    if context in ['오버이어', '온이어']:
        return render_board(HEADPHONE_BOARDS['오버이어'])
    if context in ['인이어', '오픈이어']:
        return render_board(HEADPHONE_BOARDS['인이어'])
    if context == '헤드셋(게이밍)':
        return render_board(HEADPHONE_BOARDS['헤드셋'])
    return 'CONTEXT_SELECT:' + '/'.join(HEADPHONE_CONTEXTS)
