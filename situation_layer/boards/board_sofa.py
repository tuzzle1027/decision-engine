# 소파 상황판

SOFA_BOARD = [
    ('소재', ['가죽', '패브릭', '기능성패브릭', '벨벳', '마이크로화이버']),
    ('형태', ['2인용', '3인용', '4인용이상']),
    ('구조', ['일자형', 'ㄱ자형', '모듈형']),
    ('쿠션', ['푹신', '중간', '탄탄']),
    ('브랜드', ['국내', '해외', '이케아', '상관없음']),
    ('가격', ['30만원이하', '30~100만원', '100만원이상']),
    ('직접입력', []),
]

SOFA_IKEA_BOARD = [
    ('소재', ['패브릭', '가죽', '부클레', '기능성']),
    ('형태', ['2인용', '3인용', '코너형', '모듈형']),
    ('기능', ['일반', '소파베드', '수납형']),
    ('컬러', ['베이지', '그레이', '블랙', '기타']),
    ('조립', ['직접조립', '조립대행', '상관없음']),
    ('가격', ['30만원이하', '30~70만원', '70~150만원', '150만원이상']),
    ('직접입력', []),
]


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    if context == '이케아':
        return render_board(SOFA_IKEA_BOARD)
    return render_board(SOFA_BOARD)
