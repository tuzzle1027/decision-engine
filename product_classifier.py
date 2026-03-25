# ===============================
# product_classifier.py
# 공산품 판단 모듈
# 동현님 설계 / 로드 구현
# ===============================
#
# 역할:
# LLM에게 공산품 여부 판단 요청
# YES → 상황판 진입
# NO  → "쇼핑 도우미예요" 안내
#
# 나중에 추가:
# 카테고리 분류 (전자제품/패션/식품 등)
# 카테고리별 상황판 분기
# ===============================

import os
import json
import urllib.request

OPENAI_API_KEY = os.environ.get(
    'OPENAI_API_KEY',
    ''
)

# ===============================
# 공산품 판단 시스템 프롬프트
# ===============================
CLASSIFIER_SYSTEM = """
당신은 쇼핑 AI의 입력 분류기입니다.
사용자 입력이 "구매 가능한 공산품"인지 판단하세요.

공산품 기준:
- 온라인/오프라인에서 구매 가능한 제품
- 노트북, 가방, 냉장고, 신발, 의자, 책상 등
- 브랜드나 모델명도 포함

공산품 아닌 것:
- 장소 (롯데월드, 맛집, 호텔)
- 서비스 (여행, 배달)
- 날씨, 뉴스, 정보 검색
- 추상적 개념

JSON만 출력하세요 (다른 텍스트 없이):
{
  "is_product": true 또는 false,
  "product_name": "제품명 (있으면)",
  "category": "카테고리 (전자제품/패션/생활용품/기타)",
  "reason": "판단 이유 한 줄"
}
"""

def call_llm_classifier(text):
    """LLM으로 공산품 판단"""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'max_tokens': 200,
        'messages': [
            {'role': 'system', 'content': CLASSIFIER_SYSTEM},
            {'role': 'user', 'content': f'입력: {text}'}
        ]
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body, headers=headers, method='POST'
    )
    try:
        res    = urllib.request.urlopen(req)
        result = json.loads(res.read().decode('utf-8'))
        raw    = result['choices'][0]['message']['content'].strip()

        # JSON 파싱
        if '```' in raw:
            import re
            raw = re.sub(r'```json|```', '', raw).strip()
        return json.loads(raw)

    except Exception as e:
        # LLM 오류 시 기본값 (공산품으로 처리)
        return {
            'is_product': True,
            'product_name': text,
            'category': '기타',
            'reason': f'분류 오류: {e}'
        }


# ===============================
# 빠른 키워드 사전 검사
# LLM 호출 전 먼저 확인 (비용 절약)
# ===============================
NON_PRODUCT_KEYWORDS = [
    # 장소
    '롯데월드', '에버랜드', '맛집', '식당', '카페', '호텔', '펜션',
    '관광', '공항', '지하철', '버스',
    # 날씨/뉴스
    '날씨', '기온', '뉴스', '주식', '환율',
    # 추상
    '사랑', '행복', '고민', '상담', '심리',
]

PRODUCT_KEYWORDS = [
    # 전자제품
    '노트북', '핸드폰', '폰', '태블릿', '모니터', '키보드', '마우스',
    '냉장고', '세탁기', '에어컨', 'TV', '청소기', '공기청정기',
    # 패션
    '가방', '신발', '옷', '티셔츠', '바지', '자켓', '코트',
    # 생활
    '의자', '책상', '소파', '침대', '매트리스',
    '캐리어', '트롤리', '여행가방', '캐리어백',
    # 기타
    'laptop', 'phone', 'bag', 'shoes',
]

def quick_check(text):
    """
    키워드 사전 검사 (LLM 호출 전)
    확실한 경우만 처리, 애매하면 None 반환
    """
    text_lower = text.lower()

    # 확실히 공산품 아닌 것
    for kw in NON_PRODUCT_KEYWORDS:
        if kw in text_lower:
            return {
                'is_product': False,
                'product_name': '',
                'category': '비공산품',
                'reason': f'{kw} 감지'
            }

    # 확실히 공산품인 것
    for kw in PRODUCT_KEYWORDS:
        if kw in text_lower:
            return {
                'is_product': True,
                'product_name': kw,
                'category': '확인필요',
                'reason': f'{kw} 감지'
            }

    # 애매하면 None → LLM에게 물어보기
    return None


# ===============================
# 메인 분류 함수
# ===============================
def classify_product(text):
    """
    공산품 여부 판단
    1. 키워드 사전 검사 (빠름)
    2. LLM 판단 (정확함)

    반환:
    {
        'is_product': True/False,
        'product_name': '제품명',
        'category': '카테고리',
        'reason': '이유'
    }
    """
    # 1단계: 빠른 키워드 검사
    quick = quick_check(text)
    if quick is not None:
        return quick

    # 2단계: LLM 판단
    return call_llm_classifier(text)


# ===============================
# 비공산품 응답 메시지
# ===============================
def get_out_of_scope_message():
    return (
        "저는 제품 선택을 도와주는 쇼핑 AI예요 😊\n\n"
        "노트북, 가방, 냉장고처럼 구매하고 싶은 제품을 알려주시면\n"
        "리뷰와 수치를 기반으로 최적의 제품을 찾아드려요!\n\n"
        "어떤 제품을 찾고 계신가요?"
    )


# ===============================
# 테스트
# ===============================
if __name__ == '__main__':
    tests = [
        '냉장고',
        '롯데월드',
        '발열 없는 노트북 찾아줘',
        '맛집 추천해줘',
        '가성비 좋은 가방',
        '날씨 어때',
        '아이 독서대',
        '여행용 캐리어',
    ]

    print("공산품 분류 테스트")
    print("=" * 40)
    for t in tests:
        result = classify_product(t)
        icon = "✅" if result['is_product'] else "❌"
        print(f"{icon} {t}")
        print(f"   → {result['reason']}")
        print()
