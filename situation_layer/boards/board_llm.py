# LLM 폴백 상황판
# 하드코딩에 없는 제품 → LLM이 동적으로 생성

import os
import json
import urllib.request
import re


BOARD_PROMPT = """사용자가 "{product}" 구매 상황판을 만들어주세요.

반드시 아래 형식으로만 출력하세요:

[항목명1]
옵션1 / 옵션2 / 옵션3

[항목명2]
옵션1 / 옵션2 / 옵션3

[가격]
저가 / 중가 / 고가

[E 직접입력]
원하는 조건을 자유롭게 입력하세요

핵심 규칙:
- 반드시 실제 시장에서 판매되는 제품 스펙 기반으로 작성
- 감이나 추측으로 만들지 말 것
- 해당 제품의 실제 구매 기준이 되는 항목만 (3~6개)
- 물리적으로 불가능하거나 해당 제품에 맞지 않는 옵션 금지
  (예: 유아 책상에 강화유리 ❌, 커튼에 변속단수 ❌)
- 옵션 텍스트 안에 슬래시(/) 절대 금지
- 구분선(---) 절대 출력 금지
- 다른 텍스트 없이 형식만 출력
- 항목 순서: 크기/용량 → 기능/성능 → 소재/재질 → 색상 → 가격
- [E 직접입력] 항목에는 절대 옵션 추가 금지! 반드시 "원하는 조건을 자유롭게 입력하세요" 그대로"""


def _call_anthropic(prompt: str) -> str:
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return ''
    try:
        body = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 400,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body,
            headers={'Content-Type': 'application/json',
                     'x-api-key': api_key,
                     'anthropic-version': '2023-06-01'},
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        return data['content'][0]['text'].strip()
    except Exception as e:
        print(f'[LLM 폴백 오류] {e}')
        return ''


def _call_openai(prompt: str) -> str:
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return ''
    try:
        body = json.dumps({
            'model': 'gpt-4o-mini',
            'max_tokens': 400,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=body,
            headers={'Content-Type': 'application/json',
                     'Authorization': f'Bearer {api_key}'},
            method='POST'
        )
        res = urllib.request.urlopen(req, timeout=5)
        data = json.loads(res.read())
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f'[OpenAI 폴백 오류] {e}')
        return ''


def get_board(product: str = '', context: str = None, choice: str = None) -> str:
    """
    동적 상황판 생성
    1순위: 네이버 패턴 분석 (실제 데이터 기반)
    2순위: LLM 감 (폴백)
    """
    # 0순위: 소파 MASTER_SCHEMA (테스트: 3인용 패브릭 소파 전용)
    if product and '소파' in product:
        try:
            from naver_api import get_sofa_board_schema
            schema_board = get_sofa_board_schema(product)
            if schema_board and '[' in schema_board:
                print(f'[스키마상황판] {product} MASTER_SCHEMA 사용!')
                return schema_board
        except Exception as e:
            print(f'[스키마오류] {e}')

    # 1순위: 네이버 패턴 분석 (소파 외 제품)
    if product:
        try:
            from naver_api import get_board_pattern
            pattern_board = get_board_pattern(product)
            if pattern_board and '[' in pattern_board:
                print(f'[패턴상황판] {product} 네이버 패턴 사용!')
                if '[E 직접입력]' not in pattern_board:
                    pattern_board = pattern_board.rstrip() + '\n\n[E 직접입력]\n원하는 조건을 자유롭게 입력하세요'
                # 색상 항목 금지 단어 후처리 제거
                # 가격 0만원 후처리
                import re as _re_price
                pattern_board = _re_price.sub(r'0만원~', '', pattern_board)
                pattern_board = _re_price.sub(r'0만원', '5만원이하', pattern_board)

                # ★ 가격 형식 변환: "1만원~3만원" → "저가|1만원~3만원"
                _grade_labels = ['저가', '중가', '고가', '최고가']
                _lines2 = pattern_board.split('\n')
                _in_price2 = False
                _grade_idx = 0
                _converted = []
                for _line in _lines2:
                    if _line.strip().startswith('[가격]'):
                        _in_price2 = True
                        _grade_idx = 0
                        _converted.append(_line)
                        continue
                    if _in_price2 and _line.strip().startswith('['):
                        _in_price2 = False
                    if _in_price2 and _line.strip():
                        opts = [o.strip() for o in _line.split('/') if o.strip()]
                        new_opts = []
                        for opt in opts:
                            if any(g in opt for g in _grade_labels):
                                new_opts.append(opt)
                            elif _grade_idx < len(_grade_labels):
                                new_opts.append(f'{_grade_labels[_grade_idx]}|{opt}')
                                _grade_idx += 1
                            else:
                                new_opts.append(opt)
                        _converted.append(' / '.join(new_opts))
                        continue
                    _converted.append(_line)
                pattern_board = '\n'.join(_converted)


                EXCLUDE_COLOR = {'기타', '기타색상', '기타색', '혼합', '믹스', '무지개', '컬러', '패턴', '프린트'}
                lines = pattern_board.split('\n')
                in_color = False
                cleaned = []
                for line in lines:
                    if line.startswith('[색상]') or line.startswith('[색상계열]'):
                        in_color = True
                        cleaned.append(line)
                    elif line.startswith('[') and in_color:
                        in_color = False
                        cleaned.append(line)
                    elif in_color and '/' in line:
                        opts = [o.strip() for o in line.split('/') if o.strip() not in EXCLUDE_COLOR]
                        if opts:
                            cleaned.append(' / '.join(opts))
                    else:
                        cleaned.append(line)
                pattern_board = '\n'.join(cleaned)
                return pattern_board
        except Exception as e:
            print(f'[패턴상황판오류] {e}')

    # 실제 가격 구간 힌트
    price_hint = ''
    if product:
        try:
            from naver_api import get_price_range
            price_ranges = get_price_range(product)
            if price_ranges and len(price_ranges) >= 3:
                price_str = ' / '.join(price_ranges[:4])
                price_hint = '\n\n[가격 구간 힌트] 네이버 실제 가격 기준: ' + price_str + '\n→ [가격] 항목은 반드시 위 가격 구간을 그대로 사용하세요. 저가/중가/고가 사용 금지!'
        except Exception as e:
            print(f'[LLM폴백 가격구간오류]', e)
    prompt = BOARD_PROMPT.format(product=product or '제품') + price_hint

    # 1차: Anthropic LLM
    result = _call_anthropic(prompt)
    if result:
        return result

    # 2차: OpenAI
    result = _call_openai(prompt)
    if result:
        return result

    # 최종 폴백
    return """[용도]
기본 / 고급 / 상관없음

[브랜드]
국내 / 해외 / 상관없음

[가격]
저가 / 중가 / 고가

[E 직접입력]
원하는 조건을 직접 입력하세요"""
