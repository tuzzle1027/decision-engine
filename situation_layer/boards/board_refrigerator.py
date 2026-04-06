# 냉장고 상황판
# 2구역: 가정 / 사무실 / 업소

REFRIGERATOR_BOARDS = {
    '가정': [
        ('용량', ['200L이하', '200~400L', '400~600L', '600L이상']),
        ('형태', ['일반형', '양문형', '4도어']),
        ('주요기능', ['기본', '냉동강화', '절전', '스마트']),
        ('소음', ['중요', '상관없음']),
        ('브랜드', ['삼성', 'LG', '위니아', '상관없음']),
        ('가격', ['50만원이하', '50~150만원', '150만원이상']),
        ('직접입력', []),
    ],
    '사무실': [
        ('용량', ['100L이하', '100~200L', '200L이상']),
        ('형태', ['일반형', '미니냉장고', '음료냉장고']),
        ('주요기능', ['기본', '절전', '잠금장치']),
        ('소음', ['중요', '상관없음']),
        ('브랜드', ['삼성', 'LG', '상관없음']),
        ('가격', ['20만원이하', '20~50만원', '50만원이상']),
        ('직접입력', []),
    ],
    '업소': [
        ('용량', ['300L이하', '300~600L', '600L이상']),
        ('형태', ['냉장고', '쇼케이스', '냉동고']),
        ('주요기능', ['냉장', '냉동', '겸용']),
        ('설치', ['스탠드형', '빌트인']),
        ('브랜드', ['대기업', '중소기업', '상관없음']),
        ('가격', ['50만원이하', '50~150만원', '150만원이상']),
        ('직접입력', []),
    ],
}

REFRIGERATOR_CONTEXTS = ['가정', '사무실', '업소']


def render_board(items):
    lines = ['조건을 선택해주세요']
    for label, options in items:
        if label == '직접입력':
            lines.append('\n[E 직접입력]\n원하는 조건을 직접 입력하세요')
        else:
            lines.append(f'\n[{label}]\n' + ' / '.join(options))
    return '\n'.join(lines)


def get_board(context: str = None, choice: str = None) -> str:
    if context and context in REFRIGERATOR_BOARDS:
        return render_board(REFRIGERATOR_BOARDS[context])
    # 없는 context → LLM 폴백
    if context and context not in REFRIGERATOR_BOARDS:
        from .board_llm import get_board as llm_b
        return llm_b(product=f'{context} 냉장고')
    return 'CONTEXT_SELECT:' + '/'.join(REFRIGERATOR_CONTEXTS)
