# ===============================
# context_manager.py
# 픽코 맥락 컨트롤러
# ===============================
#
# 역할:
#   1. 맥락 저장소 (사용자 행동 기록) ← 동현님 방식
#   2. LLM 래핑 (맥락 자동 주입)     ← 로드 방식
#   둘 다 합쳐서 완성!
#
# 사용법:
#   from context_manager import add_context, build_user_context, make_context_llm
#   add_context(session_id, "소파 검색")
#   _ctx = build_user_context(product, selections, direct_input, session_id)
#   call_llm = make_context_llm(call_llm, _ctx)
# ===============================

# ★ 맥락 저장소 (세션별) - 동현님 방식!
_context_store = {}


def add_context(session_id: str, event: str) -> None:
    """
    사용자 행동 기록
    상품 검색, 상황판 선택, 직접입력, 의도 질문 답변 등
    나중에 의도/고민 질문까지 여기에 쌓임!
    """
    if not session_id:
        return
    if session_id not in _context_store:
        _context_store[session_id] = []
    _context_store[session_id].append(event)
    print(f'[맥락저장] {event}')


def get_context(session_id: str) -> list:
    """전체 맥락 반환"""
    return _context_store.get(session_id, [])


def clear_context(session_id: str) -> None:
    """맥락 초기화 (새 검색 시작 시)"""
    _context_store.pop(session_id, None)


def build_user_context(
    product_name: str,
    selections: str,
    direct_input: str = '',
    session_id: str = ''
) -> str:
    """
    사용자 맥락 생성
    selections + 저장소 맥락 합산
    이 사람이 뭘 원하는지 LLM이 알게 해줌
    """
    sel_parts = []
    for part in selections.split():
        if ':' in part:
            k, v = part.split(':', 1)
            if k not in ['가격', 'E'] and v:
                sel_parts.append(v)

    context_parts = [f'{product_name} 구매 예정']
    if sel_parts:
        context_parts.append(f'선택조건: {" ".join(sel_parts[:5])}')
    if direct_input:
        context_parts.append(f'직접요청: {direct_input}')

    # ★ 저장소 맥락 추가! (쌓인 대화 이력)
    stored = get_context(session_id)
    if stored:
        context_parts.append(f'대화이력: {" → ".join(stored[-5:])}')

    return ' / '.join(context_parts)


def make_context_llm(call_llm_fn, user_context: str):
    """
    LLM 함수 래핑 - 로드 방식!
    야 LLM! 맥락 저장소 꼭 봐라! 절대 지나치지 마!
    모든 LLM 호출에 자동 주입
    퐁당퐁당 없음!
    """
    if not user_context:
        return call_llm_fn

    # 중복 래핑 방지
    if getattr(call_llm_fn, '_context_wrapped', False):
        return call_llm_fn

    def call_llm_with_context(prompt: str, **kwargs):
        context_prompt = (
            f'[구매자 맥락 - 반드시 참고! 절대 무시 금지!]\n'
            f'{user_context}\n\n'
            f'{prompt}'
        )
        return call_llm_fn(context_prompt, **kwargs)

    call_llm_with_context._context_wrapped = True
    return call_llm_with_context
