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
    board_fn = BOARD_MAP.get(product, llm_board)
    return board_fn(context=context, choice=choice)
