# ===============================
# ocr_layer.py
# 텍스트 읽기 전용 레이어
# 동현님 설계 / 로드 구현
# ===============================
#
# 핵심 철학:
# LLM이 바로 해석하면 안 된다
# 읽기만 하고 센서에 넘긴다
#
# 역할:
# 1. 텍스트 정제 (특수문자/이모지/공백)
# 2. 인코딩 오류 처리
# 3. 입력 타입 통일 (텍스트/음성/이미지 → 텍스트)
# 4. 해석 절대 금지 → 센서로 넘기기만
#
# 절대 금지:
# - LLM 호출 금지
# - 의미 해석 금지
# - 수치 계산 금지
# - 판단 금지
# ===============================

import re
import unicodedata


# ===============================
# 메인 OCR 함수
# ===============================
def ocr_layer(user_input):
    """
    사용자 입력을 읽기만 함
    LLM 없이 텍스트 정제만 수행
    해석 절대 금지

    반환:
    {
        'raw':      원본 텍스트 (정제 전)
        'clean':    정제된 텍스트 (센서에 전달)
        'length':   텍스트 길이
        'has_emoji': 이모지 포함 여부
        'lang':     언어 추정 (ko/en/mixed)
        'empty':    빈 입력 여부
    }
    """
    # 입력 없으면 빈값 반환
    if not user_input:
        return {
            'raw':       '',
            'clean':     '',
            'length':    0,
            'has_emoji': False,
            'lang':      'unknown',
            'empty':     True
        }

    # 원본 보존
    raw = str(user_input)

    # 정제 순서
    clean = raw
    clean = _normalize_encoding(clean)   # 인코딩 정규화
    clean = _remove_special(clean)        # 특수문자 정제
    clean = _normalize_whitespace(clean)  # 공백 정규화
    clean = clean.strip()

    # 메타 정보 (읽기만, 해석 금지)
    has_emoji = _detect_emoji(raw)
    lang      = _detect_lang(clean)

    return {
        'raw':       raw,
        'clean':     clean,
        'length':    len(clean),
        'has_emoji': has_emoji,
        'lang':      lang,
        'empty':     len(clean) == 0
    }


# ===============================
# 정제 함수들
# 읽기/정제만 수행, 해석 금지
# ===============================

def _normalize_encoding(text):
    """유니코드 정규화 - 인코딩 오류 방지"""
    try:
        return unicodedata.normalize('NFC', text)
    except:
        return text

def _remove_special(text):
    """
    특수문자 정제
    - 이모지는 공백으로 변환 (의미 있을 수 있음)
    - 제어문자 제거
    - 나머지는 유지
    """
    # 제어문자 제거 (탭/줄바꿈은 공백으로)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[\t\n\r]', ' ', text)

    # 이모지 → 공백 (센서가 텍스트만 처리)
    emoji_pattern = re.compile(
        '[\U00010000-\U0010ffff]', flags=re.UNICODE
    )
    text = emoji_pattern.sub(' ', text)

    return text

def _normalize_whitespace(text):
    """연속 공백 → 단일 공백"""
    return re.sub(r'\s+', ' ', text).strip()

def _detect_emoji(text):
    """이모지 포함 여부 감지 (읽기만)"""
    emoji_pattern = re.compile(
        '[\U00010000-\U0010ffff]', flags=re.UNICODE
    )
    return bool(emoji_pattern.search(text))

def _detect_lang(text):
    """
    언어 추정 (읽기만, 해석 금지)
    ko: 한국어
    en: 영어
    mixed: 혼합
    """
    if not text:
        return 'unknown'
    ko_count = len(re.findall(r'[가-힣]', text))
    en_count = len(re.findall(r'[a-zA-Z]', text))
    if ko_count > 0 and en_count == 0:   return 'ko'
    if en_count > 0 and ko_count == 0:   return 'en'
    if ko_count > 0 and en_count > 0:    return 'mixed'
    return 'unknown'


# ===============================
# 확장: 다른 입력 타입 처리
# 음성/이미지 → 텍스트 변환 후 ocr_layer로
# ===============================

def ocr_from_voice(audio_text):
    """
    음성 → 텍스트 변환 후 처리
    (실제 STT는 외부 API 사용)
    지금은 텍스트로 받아서 정제만
    """
    return ocr_layer(audio_text)

def ocr_from_image(image_text):
    """
    이미지에서 추출된 텍스트 처리
    (실제 OCR은 외부 API 사용)
    지금은 텍스트로 받아서 정제만
    """
    return ocr_layer(image_text)


# ===============================
# 테스트
# ===============================
if __name__ == '__main__':
    tests = [
        "노트북 발열 없는 거 찾아줘",
        "가방 사고 싶은데 비싸고 여행 갈지도 몰라 😅",
        "  공백   많은   입력  ",
        "",
        "laptop no heat please recommend",
        "노트북 추천 please help me 혼합",
    ]

    print("OCR 레이어 테스트")
    print("="*40)
    for t in tests:
        result = ocr_layer(t)
        print(f"입력: {repr(t[:30])}")
        print(f"  clean: {result['clean']}")
        print(f"  lang:  {result['lang']}")
        print(f"  emoji: {result['has_emoji']}")
        print(f"  empty: {result['empty']}")
        print()
