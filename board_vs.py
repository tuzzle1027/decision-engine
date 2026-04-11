# ===============================
# board_vs.py v3
# VS 비교 모드 - 상황별 카드 구조
# 동현님 설계 / 로드 구현
#
# 핵심 철학:
# 1. VS 감지 (두 제품 추출)
# 2. 상황별 카드 생성 (LLM)
# 3. 사용자가 보고 스스로 판단
# 4. 선택 → 기존 상황판 흐름
#
# "좋은 컨텐츠가 좋은 선택을 만든다"
# ===============================

import re
import json


# ── 1단계: VS 감지 ──

def detect_vs(text: str):
    """
    VS 감지 + 두 제품 LLM 추출

    공식:
    제품 1개 + 살까말까 → 반의도 (None)
    제품 2개 + 비교신호 → VS (scenario_key)

    A-1/A-2: 가죽소파|패브릭소파 (같은 카테고리)
    A-1/B-1: 소파|침대 (다른 카테고리)
    """
    # 강한 VS 신호 (살까 개수 무관하게 VS)
    STRONG_VS_SIGNALS = [
        'vs', 'VS', '중 어떤', '중에 어떤', '중 뭐가',
        '둘 중', '어느게 나을', '어느것이 나을',
        '뭐가 나을까', '어떤게 나을까',
        '와 중에', '랑 중에',
    ]
    has_strong_signal = any(kw in text for kw in STRONG_VS_SIGNALS)

    # "살까" 2개 이상 = VS
    salka_count = text.count('살까')
    if salka_count >= 2:
        has_signal = True
    elif salka_count == 1 and not has_strong_signal:
        # 살까 1개 + 강한 신호 없으면 → 반의도
        return None
    else:
        # 기타 VS 신호
        VS_SIGNALS = [
            '좋을까', '나을까', '비교', '차이',
            '어떤게', '뭐가', '골라', '어느게',
            '어느것', '먼저', '어떤것이', '어떤거를',
        ]
        has_signal = has_strong_signal or any(kw in text for kw in VS_SIGNALS)

    if not has_signal and not has_strong_signal:
        return None

    try:
        from main import call_llm
        prompt = f"""문장: "{text}"

비교하는 두 가지를 추출하세요.

규칙:
- 같은 카테고리 OK: 가죽소파|패브릭소파
- 다른 카테고리 OK: 소파|침대, 옷장|책상
- 비교가 아니거나 하나만 있으면: NONE

형식: 제품A|제품B
한 줄만 출력."""

        result = call_llm(prompt, max_tokens=20).strip()
        if result == 'NONE' or '|' not in result:
            return None
        parts = result.split('|')
        if len(parts) >= 2:
            a, b = parts[0].strip(), parts[1].strip()
            if a and b and a != b:
                print(f'[VS감지] {a} vs {b}')
                return f'{a}|||{b}'
    except Exception as e:
        print(f'[VS감지오류] {e}')
    return None


# ── 2단계: 상황별 카드 생성 ──

def generate_situation_cards(product_a: str, product_b: str, context_summary: str = '') -> list:
    """
    LLM이 두 제품의 상황별 카드 생성

    context_summary: 사용자 대화 맥락 요약
    → 있으면 맥락 반영 카드
    → 없으면 기본 카드
    """
    try:
        from main import call_llm

        # 맥락 있으면 반영
        context_part = ''
        if context_summary:
            context_part = f"""
[사용자 대화 맥락]
{context_summary}
→ 위 맥락을 반드시 상황 카드에 반영하세요.
"""

        prompt = f"""제품A: {product_a}
제품B: {product_b}
{context_part}
두 제품을 비교할 때 소비자가 고민하는 상황 3~4가지를 만들어주세요.
각 상황에서 두 제품의 장단점을 작성하세요.

형식 (정확히):
이모지|상황제목|A장점1,A단점1,A장점2|B장점1,B단점1,B장점2

규칙:
- 장점은 +로 시작, 단점은 -로 시작
- 각 제품 장단점 2~3개
- 이모지는 상황에 맞게
- 한국어로
- 3~4줄만 출력
- 맥락이 있으면 맥락 상황을 첫 번째 카드로!

예시:
🐶|반려동물 있을 때|+발톱 스크래치 강함,-털 쉽게 붙음|+털 안붙고 닦기 쉬움,-발톱 스크래치 약함
🍕|음식물 묻었을 때|-액체 스며들 수 있음,+커버 세탁 가능|+바로 닦으면 OK,+얼룩 잘 안생김
👶|아이 있을 때|+푹신해서 안전,+따뜻함,-오염 주의|+청소 빠름,-여름 달라붙음
🌡️|여름/겨울 온도|+사계절 쾌적,-여름 땀 흡수|+겨울도 따뜻,-여름 달라붙음"""

        result = call_llm(prompt, max_tokens=400).strip()
        cards = []

        for line in result.split('\n'):
            line = line.strip()
            if '|' not in line:
                continue
            parts = line.split('|')
            if len(parts) < 4:
                continue

            emoji = parts[0].strip()
            title = parts[1].strip()

            # A 제품 장단점 파싱
            a_items = []
            for item in parts[2].split(','):
                item = item.strip()
                if item.startswith('+'):
                    a_items.append({'good': True, 'text': item[1:].strip()})
                elif item.startswith('-'):
                    a_items.append({'good': False, 'text': item[1:].strip()})

            # B 제품 장단점 파싱
            b_items = []
            for item in parts[3].split(','):
                item = item.strip()
                if item.startswith('+'):
                    b_items.append({'good': True, 'text': item[1:].strip()})
                elif item.startswith('-'):
                    b_items.append({'good': False, 'text': item[1:].strip()})

            if emoji and title and a_items and b_items:
                cards.append({
                    'emoji': emoji,
                    'title': title,
                    'a': a_items,
                    'b': b_items,
                })

        print(f'[VS카드생성] {len(cards)}개')
        return cards

    except Exception as e:
        print(f'[VS카드생성오류] {e}')
        return []


# ── 3단계: VS 응답 생성 ──

def get_vs_response(scenario_key: str, cards: list) -> str:
    """
    VS 카드 데이터를 JSON으로 반환
    app.js에서 렌더링
    """
    if '|||' not in scenario_key:
        return None

    product_a, product_b = scenario_key.split('|||')

    result = {
        'product_a': product_a,
        'product_b': product_b,
        'cards': cards,
    }

    return f"VS_CARDS:{json.dumps(result, ensure_ascii=False)}"


# ── 공개 인터페이스 ──

def get_vs_first_question(scenario_key: str, context_summary: str = '') -> str:
    """
    VS 카드 생성 후 반환
    context_summary: 사용자 대화 맥락
    """
    if '|||' not in scenario_key:
        return None

    product_a, product_b = scenario_key.split('|||')
    cards = generate_situation_cards(product_a, product_b, context_summary)

    if not cards:
        return None

    return get_vs_response(scenario_key, cards)


def get_vs_next_question(scenario_key: str, answers: dict) -> str:
    """VS는 카드 보여주기만 → 사용자 선택 대기"""
    return None
