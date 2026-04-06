# 캠핑 상황판

CAMPING_TYPES = ['백패킹', '오토캠핑', '글램핑', '차박', '카라반']
CAMPING_ITEMS = ['텐트', '침낭', '버너', '조명', '의자/테이블', '기타용품']

CAMPING_BOARDS = {
    '텐트': [
        ('형태', ['돔형', '터널형', '티피형', '원터치']),
        ('인원', ['1~2인', '3~4인', '5인이상']),
        ('계절', ['3계절', '동계', '사계절']),
        ('브랜드', ['코베아', '헬리녹스', '콜맨', '상관없음']),
        ('가격', ['10만원이하', '10~30만원', '30만원이상']),
        ('직접입력', []),
    ],
    '침낭': [
        ('계절', ['여름용', '3계절', '동계용']),
        ('형태', ['머미형', '사각형']),
        ('브랜드', ['코베아', '몽벨', '상관없음']),
        ('가격', ['5만원이하', '5~15만원', '15만원이상']),
        ('직접입력', []),
    ],
    '버너': [
        ('종류', ['가스버너', '알코올버너', '전기버너']),
        ('용도', ['1인용', '가족용', '대용량']),
        ('브랜드', ['코베아', '스노우피크', '상관없음']),
        ('가격', ['3만원이하', '3~10만원', '10만원이상']),
        ('직접입력', []),
    ],
    '조명': [
        ('종류', ['랜턴', 'LED조명', '헤드랜턴']),
        ('전원', ['배터리', '충전식', '가스']),
        ('브랜드', ['코베아', '블랙다이아몬드', '상관없음']),
        ('가격', ['3만원이하', '3~10만원', '10만원이상']),
        ('직접입력', []),
    ],
}


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    if context in CAMPING_TYPES:
        return 'CONTEXT_SELECT:' + '/'.join(CAMPING_ITEMS)
    if context and context in CAMPING_BOARDS:
        return render_board(CAMPING_BOARDS[context])
    # 없는 context → LLM 폴백
    if context and context not in CAMPING_TYPES and context not in CAMPING_BOARDS:
        from .board_llm import get_board as llm_b
        return llm_b(product=f'캠핑 {context}')
    return 'CONTEXT_SELECT:' + '/'.join(CAMPING_TYPES)
