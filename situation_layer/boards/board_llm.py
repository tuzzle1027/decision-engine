# LLM 폴백 상황판
# 하드코딩에 없는 제품 → LLM이 동적으로 생성

import os
import json
import urllib.request
import re


BOARD_PROMPT = """사용자가 "{product}" 구매 상황판을 만들어주세요.

반드시 아래 형식으로만 출력하세요:
----------------------------

[항목명1]
옵션1 / 옵션2 / 옵션3

[항목명2]
옵션1 / 옵션2 / 옵션3

[가격]
저가 / 중가 / 고가

[E 직접입력]
원하는 조건을 자유롭게 입력하세요

----------------------------

규칙:
- 실제 구매 기준이 되는 항목만 (3~5개)
- 물리적으로 불가능한 옵션 금지
- 옵션 텍스트 안에 슬래시(/) 절대 금지 (예: 3/4사이즈 ❌ → 3-4사이즈 ✅)
- 다른 텍스트 없이 형식만 출력"""


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
    """LLM으로 동적 상황판 생성"""
    prompt = BOARD_PROMPT.format(product=product or '제품')

    # 1차: Anthropic
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
