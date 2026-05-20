"""
ScrapingBee 테스트
네이버 쇼핑 리뷰 페이지 접근 가능한지 확인

준비:
1. https://app.scrapingbee.com 가입 (무료 1000 크레딧)
2. API 키 복사
3. 아래 API_KEY에 입력 후 실행
"""

import urllib.request
import urllib.parse
import json
import re

# Railway 환경변수에서 읽기
import os
SCRAPINGBEE_API_KEY = os.environ.get('SCRAPINGBEE_API_KEY', '')

# 테스트할 네이버 쇼핑 리뷰 URL
# (네이버 쇼핑에서 아무 제품 → 리뷰 탭 URL)
TEST_PRODUCT_URL = 'https://search.shopping.naver.com/catalog/33557708460'

def test_scrapingbee(target_url):
    """ScrapingBee로 네이버 리뷰 페이지 접근 테스트"""

    # ScrapingBee API 호출
    params = urllib.parse.urlencode({
        'api_key': SCRAPINGBEE_API_KEY,
        'url': target_url,
        'render_js': 'true',      # JS 렌더링 (리뷰는 JS로 로드됨)
        'premium_proxy': 'true',  # 프리미엄 프록시 (차단 우회)
        'country_code': 'kr',     # 한국 IP 사용
    })

    api_url = f'https://app.scrapingbee.com/api/v1/?{params}'

    print(f'ScrapingBee 요청 중...')
    print(f'대상: {target_url}')
    print()

    try:
        req = urllib.request.Request(api_url)
        res = urllib.request.urlopen(req, timeout=30)
        html = res.read().decode('utf-8')

        print(f'✅ 성공! HTML 크기: {len(html)} bytes')
        print()

        # 리뷰 키워드 검색
        review_keywords = ['리뷰', '후기', '별점', 'reviewContent', 'review_count']
        for kw in review_keywords:
            count = html.count(kw)
            if count > 0:
                print(f'  "{kw}" 발견: {count}회')

        # 실제 리뷰 텍스트 추출 시도
        review_pattern = re.findall(r'"reviewContent"\s*:\s*"([^"]+)"', html)
        if review_pattern:
            print(f'\n🎉 리뷰 텍스트 발견! {len(review_pattern)}개')
            for r in review_pattern[:3]:
                print(f'  - {r[:80]}')
        else:
            print('\n리뷰 텍스트 패턴 없음 → HTML 구조 확인 필요')
            # HTML 일부 출력
            print('\nHTML 샘플 (1000자):')
            print(html[:1000])

    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        print(f'❌ HTTP {e.code}')
        print(f'응답: {body[:300]}')
    except Exception as e:
        print(f'❌ 오류: {type(e).__name__}: {e}')


def check_credits():
    """남은 크레딧 확인"""
    try:
        url = f'https://app.scrapingbee.com/api/v1/usage?api_key={SCRAPINGBEE_API_KEY}'
        res = urllib.request.urlopen(url, timeout=5)
        data = json.loads(res.read())
        print(f'크레딧 현황:')
        print(f'  남은 크레딧: {data.get("max_api_credit", 0) - data.get("used_api_credit", 0)}')
        print(f'  사용한 크레딧: {data.get("used_api_credit", 0)}')
        print(f'  총 크레딧: {data.get("max_api_credit", 0)}')
    except Exception as e:
        print(f'크레딧 확인 오류: {e}')


if __name__ == '__main__':
    print('=' * 60)
    print('ScrapingBee × 네이버 쇼핑 리뷰 테스트')
    print('=' * 60)
    print()

    if SCRAPINGBEE_API_KEY == 'YOUR_API_KEY_HERE':
        print('⚠️  API 키를 입력해주세요!')
        print()
        print('가입 방법:')
        print('1. https://app.scrapingbee.com 접속')
        print('2. 이메일로 무료 가입')
        print('3. 대시보드에서 API Key 복사')
        print('4. 이 파일 SCRAPINGBEE_API_KEY에 붙여넣기')
        print()
        print('무료 크레딧: 1,000개')
        print('테스트 1회 소모: 약 25크레딧 (JS렌더링+프리미엄프록시)')
        print('→ 약 40번 테스트 가능')
    else:
        check_credits()
        print()
        test_scrapingbee(TEST_PRODUCT_URL)

