"""
픽코 개인몰 크롤러
고도몰/카페24/메이크샵/기타 독립몰에서 옵션, 리뷰, 태그 추출
"""
import re
import time
import urllib.request
from bs4 import BeautifulSoup

# ============================================
# ★ 브랜드 자체몰 DB
# 네이버 API 상품명에서 브랜드 추출 후 자체몰 매핑
# ============================================
BRAND_MALL_DB = {
    '한샘':     {'domain': 'hanssem.com',    'type': 'hanssem'},   # mall.hanssem.com, store.hanssem.com 모두 포함
    '보루네오': {'domain': 'bifshop.co.kr',  'type': 'makeshop'},
    '자코모':   {'domain': 'jakomo.co.kr',   'type': 'independent'},
    '삼익':     {'domain': 'samickmall.com', 'type': 'independent'},
    '스코나':   {'domain': 'skona.co.kr',    'type': 'independent'},
    '리바트':   {'domain': 'livart.co.kr',   'type': 'independent'},
    '까사미아': {'domain': 'casamia.co.kr',  'type': 'independent'},
    '에싸':     {'domain': 'essa.co.kr',     'type': 'independent'},
}

def get_brand_mall(brand_name: str) -> dict | None:
    """브랜드명으로 자체몰 정보 조회"""
    for key, info in BRAND_MALL_DB.items():
        if key in brand_name or brand_name in key:
            return info
    return None


# ============================================
# ★ Anthropic web_fetch 경유 크롤링
# Railway IP 차단 시 우회 방법
# ============================================
def crawl_with_anthropic(url: str, focus: str = 'review') -> dict:
    """
    Anthropic web_fetch로 자체몰 크롤링
    2단계 방식:
    1. 상품 페이지 → 평점/리뷰수/가격 + 개별 리뷰 URL 목록
    2. 개별 리뷰 페이지 → 리뷰 텍스트 수집
    """
    import anthropic, json, re

    result = {'reviews': [], 'rating': '', 'review_count': 0,
              'options': [], 'actual_price': '', 'crawled': False}

    try:
        client = anthropic.Anthropic()

        # ── 1단계: 상품 페이지에서 기본 정보 + 리뷰 URL 추출 ──
        step1_prompt = (
            f"이 쇼핑몰 URL에서 상품 정보를 찾아 JSON으로 추출해줘.\n"
            f"URL: {url}\n\n"
            f"만약 이 URL이 검색 결과 페이지라면:\n"
            f"→ 검색 결과에서 첫 번째 실제 상품 링크를 찾아서 그 페이지로 이동해줘.\n"
            f"만약 이 URL이 상품 상세 페이지라면:\n"
            f"→ 그대로 정보를 추출해줘.\n\n"
            f"추출할 정보:\n"
            f"- rating: 평점 (예: 4.8)\n"
            f"- review_count: 총 리뷰 수 (숫자만)\n"
            f"- actual_price: 실제 판매가 (숫자만, 원 제외)\n"
            f"- discount_rate: 할인율 (숫자만, % 제외)\n"
            f"- options: 상품 옵션 목록 (배열)\n"
            f"- review_urls: 개별 리뷰 상세 페이지 URL 목록 (최대 10개, 완전한 URL로)\n\n"
            f"review_urls는 /board/view.php?bdId=...&sno=... 형태의 URL을 찾아줘.\n"
            f"JSON만 출력. 마크다운 없이."
        )

        resp1 = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1}],
            messages=[{"role": "user", "content": step1_prompt}],
            extra_headers={"anthropic-beta": "web-fetch-2025-09-10"}
        )

        text1 = ''.join(b.text for b in resp1.content if hasattr(b, 'text'))
        print(f'[자코모1단계] {text1[:200]}')

        clean1 = re.sub(r'```json|```', '', text1).strip()
        m1 = re.search(r'\{.*\}', clean1, re.S)
        step1_data = {}
        if m1:
            step1_data = json.loads(m1.group(0))
            result.update({k: v for k, v in step1_data.items() if k != 'review_urls'})
            print(f'[자코모1단계] 평점:{step1_data.get("rating")} 리뷰수:{step1_data.get("review_count")} 가격:{step1_data.get("actual_price")}')

        # ── 2단계: 개별 리뷰 페이지에서 텍스트 수집 ──
        review_urls = step1_data.get('review_urls', [])
        if review_urls:
            print(f'[자코모2단계] 개별 리뷰 {len(review_urls)}개 수집 시작')

            # URL 보정 (상대경로 → 절대경로)
            from urllib.parse import urljoin
            base_url = '/'.join(url.split('/')[:3])  # https://www.jakomo.co.kr
            review_urls = [urljoin(base_url, u) if not u.startswith('http') else u
                          for u in review_urls[:8]]  # 최대 8개

            step2_prompt = (
                f"아래 리뷰 페이지 URL들을 순서대로 방문해서 리뷰 텍스트를 수집해줘.\n"
                f"URL 목록:\n" + '\n'.join(review_urls) + '\n\n'
                f"각 페이지에서 실제 구매자 리뷰 텍스트만 추출해줘.\n"
                f"결과를 JSON 배열로: [\"리뷰1\", \"리뷰2\", ...]\n"
                f"JSON 배열만 출력. 마크다운 없이."
            )

            resp2 = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                tools=[{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": len(review_urls)}],
                messages=[{"role": "user", "content": step2_prompt}],
                extra_headers={"anthropic-beta": "web-fetch-2025-09-10"}
            )

            text2 = ''.join(b.text for b in resp2.content if hasattr(b, 'text'))
            print(f'[자코모2단계] {text2[:200]}')

            clean2 = re.sub(r'```json|```', '', text2).strip()
            m2 = re.search(r'\[.*\]', clean2, re.S)
            if m2:
                reviews = json.loads(m2.group(0))
                result['reviews'] = [r for r in reviews if r and len(r) > 10]
                print(f'[자코모2단계] 리뷰 {len(result["reviews"])}건 수집!')

        result['crawled'] = True
        print(f'[Anthropic크롤링] 완료 | 리뷰:{len(result["reviews"])}건 | 평점:{result.get("rating")}')

    except Exception as e:
        print(f'[Anthropic크롤링오류] {type(e).__name__}: {e}')

    return result


def smart_crawl(url: str, product_name: str = '', focus: str = 'review') -> dict:
    """
    스마트 크롤링:
    1. Railway 직접 시도
    2. 실패 → Anthropic web_fetch 경유
    스마트스토어/쿠팡 등 불가 도메인은 즉시 스킵
    """
    SKIP_DOMAINS = ['smartstore.naver.com', 'brand.naver.com',
                    'coupang.com', 'gmarket.co.kr', '11st.co.kr',
                    'search.shopping.naver.com']

    if any(d in url for d in SKIP_DOMAINS):
        print(f'[크롤링스킵] 지원안됨: {url[:50]}')
        return {'reviews': [], 'crawled': False}

    # 1단계: Railway 직접
    print(f'[크롤링시도] Railway 직접: {url[:60]}')
    result = crawl_product_page(url)

    if result.get('crawled') and (result.get('reviews') or result.get('rating')):
        print('[크롤링성공] Railway 직접!')
        return result

    # 2단계: Anthropic 경유
    print('[크롤링전환] Railway 실패 → Anthropic 경유')
    result = crawl_with_anthropic(url, focus=focus)

    if result.get('crawled'):
        print('[크롤링성공] Anthropic 경유!')
    else:
        print('[크롤링실패] 두 방법 모두 실패')

    return result


def crawl_brand_reviews(brand_name: str, product_name: str, product_url: str = '') -> list:
    """
    자체몰 크롤링 - 현재 비활성화
    (AJAX 동적 로딩, Railway IP 차단 등 한계로 일시 중단)
    향후 Playwright 또는 파트너십으로 재활성화 예정
    """
    print(f'[자체몰스킵] {brand_name} → 크롤링 비활성화')
    return []

def _get_mall_type(url: str) -> str:
    if 'smartstore.naver.com' in url or 'brand.naver.com' in url:
        return 'smartstore'
    if 'cafe24.com' in url:
        return 'cafe24'
    if 'shopdetail.html' in url and 'branduid' in url:
        return 'makeshop'
    if 'goods_view.php' in url or 'goodsNo' in url:
        return 'godo'
    if 'coupang.com' in url:
        return 'coupang'
    if 'gmarket.co.kr' in url or 'auction.co.kr' in url:
        return 'open_market'
    return 'independent'

def _is_crawlable(url: str) -> bool:
    """Railway 직접 크롤링 가능한 URL인지 판별"""
    blocked = [
        'smartstore.naver.com', 'brand.naver.com',
        'coupang.com',
        'gmarket.co.kr', 'auction.co.kr',
        '11st.co.kr', 'interpark.com',
        # cafe24, godo는 Anthropic 경유로 처리 (여기선 차단 안 함)
    ]
    return not any(d in url for d in blocked)

def crawl_product_page(url: str, timeout: int = 5) -> dict:
    """개인몰 상품페이지 크롤링 → 옵션/리뷰/태그 반환"""
    result = {
        'options': [],
        'reviews': [],
        'tags': [],
        'rating': '',
        'review_count': 0,
        'mall_type': _get_mall_type(url),
        'crawled': False,
    }

    if not _is_crawlable(url):
        print(f'[크롤링스킵] 차단된 도메인: {url[:50]}')
        return result

    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate',
            }
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        html = resp.read()
        # 인코딩 처리
        try:
            html = html.decode('utf-8')
        except:
            try:
                html = html.decode('euc-kr')
            except:
                html = html.decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, 'html.parser')
        result['crawled'] = True

        # ── 1. 옵션 추출 (select/option 태그) ──
        for select in soup.find_all('select'):
            name = select.get('name', '') or select.get('id', '')
            if any(k in name.lower() for k in ['option', 'opt', 'color', 'size', 'type']):
                for opt in select.find_all('option'):
                    text = opt.get_text(strip=True)
                    # 선택/필수 등 안내 문구 제거
                    if text and len(text) > 1 and not any(skip in text for skip in
                        ['선택', '필수', '==', '--', '옵션', '색상선택', '사이즈선택']):
                        result['options'].append(text)

        # 모든 select에서도 추출 (옵션명 포함 가능성)
        if not result['options']:
            for select in soup.find_all('select'):
                for opt in select.find_all('option'):
                    text = opt.get_text(strip=True)
                    if 2 < len(text) < 50 and not any(skip in text for skip in
                        ['선택', '==', '--', '필수']):
                        result['options'].append(text)

        result['options'] = list(dict.fromkeys(result['options']))[:20]

        # ── 3. 실제 가격 (lprice 0원 문제 해결!) ──
        PRICE_SELECTORS = [
            '.sale_price', '.sell_price', '.goods_price',
            '.price_sale', '#sell_price', '.real_price',
            'strong.price', '.final_price', '.discount_price',
        ]
        for sel in PRICE_SELECTORS:
            el = soup.select_one(sel)
            if el:
                price_text = el.get_text(strip=True).replace(',', '').replace('원', '').strip()
                price_nums = re.findall(r'\d{4,}', price_text)
                if price_nums:
                    result['actual_price'] = f'{int(price_nums[0]):,}원'
                    print(f'[실제가격] {result["actual_price"]}')
                    break

        # ── 4. 별점/리뷰 수 ──
        REVIEW_SELECTORS = [
            # 고도몰
            '.review_content', '.review-content', '#reviewContent',
            # 카페24
            '.review-list .cont', '.xans-review-listnormal',
            # 메이크샵
            '.reply_text', '.reply-text', '.review_txt',
            # 공통
            '[class*="review_cont"]', '[class*="review-cont"]',
            '[class*="comment_cont"]', '[class*="review_text"]',
            '.board_view_content', '.bbs_content',
        ]
        seen_reviews = set()
        for sel in REVIEW_SELECTORS:
            for el in soup.select(sel)[:5]:
                text = el.get_text(strip=True)
                text = re.sub(r'\s+', ' ', text)
                if len(text) > 20 and text not in seen_reviews:
                    seen_reviews.add(text)
                    result['reviews'].append(text[:300])
            if len(result['reviews']) >= 5:
                break

        # ── 3. 별점/리뷰 수 ──
        # 고도몰 패턴
        rating_el = soup.select_one('.star_score, .rating_score, .review_star, [class*="star_avg"]')
        if rating_el:
            rating_text = rating_el.get_text(strip=True)
            nums = re.findall(r'\d+\.?\d*', rating_text)
            if nums:
                result['rating'] = nums[0]

        count_el = soup.select_one('.review_cnt, .review_count, [class*="review_num"]')
        if count_el:
            count_text = count_el.get_text(strip=True)
            nums = re.findall(r'\d+', count_text.replace(',', ''))
            if nums:
                result['review_count'] = int(nums[0])

        # ── 4. 메타 태그에서 키워드 ──
        meta_kw = soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            result['tags'] = [t.strip() for t in meta_kw['content'].split(',') if t.strip()][:10]

        # ── 5. 상품 설명 텍스트 (이미지 제외) ──
        desc_text = []
        for tag in soup.find_all(['p', 'li', 'td', 'span']):
            text = tag.get_text(strip=True)
            if 10 < len(text) < 150 and text not in desc_text:
                desc_text.append(text)
        if desc_text:
            result['description_text'] = ' '.join(desc_text[:10])

        print(f'[크롤링완료] {_get_mall_type(url)} | 옵션:{len(result["options"])}개 | 리뷰:{len(result["reviews"])}개 | 태그:{len(result["tags"])}개')

    except Exception as e:
        print(f'[크롤링오류] {url[:60]}: {e}')

    return result


def find_independent_mall_url(product_name: str, timeout: int = 5) -> str:
    """
    제품명/브랜드명으로 메이크샵/고도몰 독립몰 URL 찾기
    브랜드명 검색 우선 → 없으면 제품명 전체
    """
    import os, urllib.request, urllib.parse, json, re

    NID = os.environ.get('NAVER_CLIENT_ID', '')
    NIS = os.environ.get('NAVER_CLIENT_SECRET', '')
    if not NID:
        return ''

    MALL_PATTERNS = [
        r'https?://[^\s"\'<>]+/shop/shopdetail\.html[^\s"\'<>]*',  # 메이크샵
        r'https?://[^\s"\'<>]+/goods/goods_view\.php[^\s"\'<>]*',  # 고도몰
    ]
    SKIP_DOMAINS = [
        'smartstore.naver.com', 'brand.naver.com',
        'cafe24.com', 'coupang.com', 'gmarket.co.kr',
        'auction.co.kr', '11st.co.kr', 'shopping.naver.com',
        'search.shopping.naver.com', 'ohou.se', 'hanssem.com',
    ]

    # 브랜드명 추출 (첫 단어 or 2단어)
    words = product_name.strip().split()
    brand_queries = []
    if len(words) >= 1:
        brand_queries.append(words[0])           # "비쥬"
    if len(words) >= 2:
        brand_queries.append(' '.join(words[:2])) # "비쥬 케이시"
    brand_queries.append(product_name)            # 전체 (마지막 시도)

    for query in brand_queries:
        try:
            enc = urllib.parse.quote(query)
            # 웹문서 API: 쇼핑보다 독립몰 발견율 높음 (파워링크 포함!)
            url = f'https://openapi.naver.com/v1/search/webkr.json?query={enc}&display=10'
            req = urllib.request.Request(url, headers={
                'X-Naver-Client-Id': NID,
                'X-Naver-Client-Secret': NIS,
            })
            resp = urllib.request.urlopen(req, timeout=timeout)
            items = json.loads(resp.read()).get('items', [])

            for item in items:
                link = item.get('link', '')
                if not link or any(d in link for d in SKIP_DOMAINS):
                    continue
                for pattern in MALL_PATTERNS:
                    if re.search(pattern, link):
                        print(f'[독립몰발견] 쿼리="{query}" → {link[:70]}')
                        return link
                # 메이크샵/고도몰 패턴 없으면 스킵 (오늘의집/한샘 등 제외)

        except Exception as e:
            print(f'[독립몰검색오류] {e}')
            break  # API 오류면 더 시도 불필요

    return ''
    """
    크롤링 결과에서 사용자 조건 매칭
    options + tags + description에서 조건값 검색
    """
    all_text = ' '.join(
        crawl_result.get('options', []) +
        crawl_result.get('tags', []) +
        [crawl_result.get('description_text', '')]
    ).lower()

    matched = []
    unmatched = []
    for sel in user_selections:
        if sel.lower() in all_text:
            matched.append(sel)
        else:
            unmatched.append(sel)

    return {
        'matched': matched,
        'unmatched': unmatched,
        'match_rate': len(matched) / len(user_selections) if user_selections else 0,
        'all_text_preview': all_text[:200],
    }


def extract_conditions_from_crawl(crawl_result: dict, user_selections: list) -> dict:
    """크롤링 결과에서 사용자 조건 매칭"""
    all_text = ' '.join(
        crawl_result.get('options', []) +
        crawl_result.get('tags', []) +
        [crawl_result.get('description_text', '')]
    ).lower()

    matched = []
    unmatched = []
    for sel in user_selections:
        if sel.lower() in all_text:
            matched.append(sel)
        else:
            unmatched.append(sel)

    return {
        'matched': matched,
        'unmatched': unmatched,
        'match_rate': len(matched) / len(user_selections) if user_selections else 0,
    }
