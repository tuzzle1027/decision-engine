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
from .board_furniture import get_board as furniture_board

BOARD_MAP = {
    # 기존
    '노트북':   notebook_board,
    '냉장고':   refrigerator_board,
    '소파':     furniture_board,  # furniture로 이전
    '쇼파':     furniture_board,
    '운동화':   shoes_board,
    '러닝화':   shoes_board,
    '청소기':   vacuum_board,
    '책':       book_board,
    '헤드폰':   headphone_board,
    '이어폰':   headphone_board,
    '수영복':   swimwear_board,
    '캠핑':     camping_board,
    '텐트':     camping_board,
    # 가구/인테리어
    '침대':     furniture_board,
    '슈퍼싱글': furniture_board,
    '퀸침대':   furniture_board,
    '킹침대':   furniture_board,
    '매트리스': furniture_board,
    '책상':     furniture_board,
    '의자':     furniture_board,
    '식탁':     furniture_board,
    '수납가구': furniture_board,
    '옷장':     furniture_board,
    '서랍장':   furniture_board,
    '책장':     furniture_board,
    '화장대':   furniture_board,
    '커튼':     furniture_board,
    '블라인드': furniture_board,
    '러그':     furniture_board,
    '카페트':   furniture_board,
    '액자':     furniture_board,
    '거울':     furniture_board,
    '화분':     furniture_board,
    '캔들':     furniture_board,
    '디퓨저':   furniture_board,
    '쿠션':     furniture_board,
    '조명':     furniture_board,
    '인테리어소품': furniture_board,
    '소품':     furniture_board,
}

def get_board(product: str, context: str = None, choice: str = None) -> str:
    """제품명으로 상황판 반환. 없으면 LLM 폴백."""
    import re

    FURNITURE_BOARDS_FNS = [furniture_board]

    def _call(fn, prod, ctx, ch):
        """furniture_board는 product 파라미터 받음, 나머지는 안 받음"""
        if fn in FURNITURE_BOARDS_FNS:
            return fn(product=prod, context=ctx, choice=ch)
        return fn(context=ctx, choice=ch)

    # 1. 제품명으로 직접 찾기
    board_fn = BOARD_MAP.get(product)
    if board_fn:
        return _call(board_fn, product, context, choice)

    # 2. context값이 제품명일 수도 있음
    if context:
        board_fn = BOARD_MAP.get(context)
        if board_fn:
            return _call(board_fn, context, None, choice)

    # 3. product 안에 알려진 제품명 포함 여부 체크 (긴 것 우선)
    sorted_keys = sorted(BOARD_MAP.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if re.search(r'(?<![가-힣])' + re.escape(key) + r'(?![가-힣])', product):
            return _call(BOARD_MAP[key], key, context, choice)

    # 4. LLM 폴백
    return llm_board(product=product, context=context, choice=choice)
