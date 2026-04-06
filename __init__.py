# Picko 상황판 모듈
from .board_notebook import get_board as notebook_board
from .board_refrigerator import get_board as refrigerator_board
from .board_sofa import get_board as sofa_board
from .board_shoes import get_board as shoes_board
from .board_vacuum import get_board as vacuum_board
from .board_book import get_board as book_board
from .board_headphone import get_board as headphone_board
from .board_swimwear import get_board as swimwear_board
from .board_camping import get_board as camping_board
from .board_llm import get_board as llm_board

BOARD_MAP = {
    '노트북':   notebook_board,
    '냉장고':   refrigerator_board,
    '소파':     sofa_board,
    '쇼파':     sofa_board,
    '운동화':   shoes_board,
    '러닝화':   shoes_board,
    '청소기':   vacuum_board,
    '책':       book_board,
    '헤드폰':   headphone_board,
    '이어폰':   headphone_board,
    '수영복':   swimwear_board,
    '캠핑':     camping_board,
    '텐트':     camping_board,
}

def get_board(product: str, context: str = None, choice: str = None) -> str:
    """제품명으로 상황판 반환. 없으면 LLM 폴백."""
    # 1. 제품명으로 직접 찾기
    board_fn = BOARD_MAP.get(product)
    if board_fn:
        return board_fn(context=context, choice=choice)

    # 2. context값이 제품명일 수도 있음 (어린이→단행본 선택 후)
    if context:
        board_fn = BOARD_MAP.get(context)
        if board_fn:
            return board_fn(context=None, choice=choice)

    # 3. product 안에 알려진 제품명 포함 여부 체크
    for key in BOARD_MAP:
        if key in product:
            return BOARD_MAP[key](context=context, choice=choice)

    # 4. LLM 폴백
    return llm_board(product=product, context=context, choice=choice)
