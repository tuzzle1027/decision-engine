# ===============================
# 리뷰 수집 장소 레이어
# 동현님 설계 / 로드 구현
# ===============================
#
# 철학:
# 엔진(어떻게 분석)과 장소(어디서 가져오나) 분리
# 장소마다 넣고 빼기 가능
# API 연결 여부에 따라 ON/OFF
#
# 장소 분류:
# 엔진1 (구조형) - 별점 + 텍스트: Amazon, Walmart, Trustpilot
# 엔진2 (텍스트형) - 텍스트만:   Reddit, YouTube, Instagram, Google
#
# 광고 필터:
# "use my code" → 제외
# "where did you get?" → 진짜 후기
# ===============================

import re
import json
import os
import urllib.request
import urllib.parse

# ===============================
# API 키
# ===============================
OPENAI_API_KEY   = os.environ.get('OPENAI_API_KEY', '')
YOUTUBE_API_KEY  = os.environ.get('YOUTUBE_API_KEY', '')
REDDIT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID', '')
REDDIT_SECRET    = os.environ.get('REDDIT_SECRET', '')
APIFY_TOKEN      = os.environ.get('APIFY_TOKEN', '')  # 인스타용


# ===============================
# 광고 필터 (공통)
# 동현님 철학: 진짜 후기만
# ===============================
AD_SIGNALS = [
    'use my code', 'link in bio', 'discount code',
    'sponsored', 'ad ', '#ad', 'gifted', 'collab',
    'sharing because i love', 'partner with',
    'promo code', 'affiliate'
]

REAL_REVIEW_SIGNALS = [
    'where did you get', 'where is this from',
    'link please', 'is this worth it',
    'i bought', 'i purchased', 'i own this',
    'after using', 'been using for',
    'honest review', 'not sponsored'
]

def is_ad(text):
    """광고 후기 필터링"""
    text_lower = text.lower()
    return any(signal in text_lower for signal in AD_SIGNALS)

def is_real_review(text):
    """진짜 후기 신호 감지"""
    text_lower = text.lower()
    return any(signal in text_lower for signal in REAL_REVIEW_SIGNALS)

def clean_text(text):
    """HTML 태그 및 특수문자 제거"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'http\S+', '', text)
    return text.strip()


# ===============================
# 베이스 컬렉터
# ===============================
class BaseCollector:
    """모든 장소 컬렉터의 기본 클래스"""
    name      = 'base'
    engine_type = 1      # 1=구조형, 2=텍스트형
    available = False    # API 연결 여부

    def collect(self, keyword, product_title='', count=10):
        """리뷰 수집 - 각 장소마다 구현"""
        raise NotImplementedError

    def format_review(self, text, score=None, source=''):
        """공통 리뷰 포맷"""
        return {
            'text':        clean_text(text),
            'score':       score,      # 별점 (없으면 None)
            'source':      source or self.name,
            'engine_type': self.engine_type,
            'is_ad':       is_ad(text),
            'is_real':     is_real_review(text)
        }


# ===============================
# 엔진1 (구조형) - 별점 + 텍스트
# ===============================

class AmazonCollector(BaseCollector):
    """
    Amazon 리뷰 수집
    상태: API 없음 → SerpAPI 또는 Apify 필요
    신뢰도: ★★★★★ (실구매자만)
    엔진타입: 1 (별점 + 텍스트)
    """
    name        = 'amazon'
    engine_type = 1
    available   = False  # Apify 연결 시 True

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        # TODO: Apify Amazon scraper 연결
        # https://apify.com/junglee/amazon-crawler
        # APIFY_TOKEN 필요
        return []

    def _mock_data(self, keyword, count):
        """테스트용 샘플 데이터"""
        return [
            self.format_review(
                "Great product! No heat issues at all after 3 months of use.",
                score=5, source='amazon'
            ),
            self.format_review(
                "Battery drains faster than expected. Otherwise good.",
                score=3, source='amazon'
            ),
            self.format_review(
                "use my code SAVE10 for discount",
                score=5, source='amazon'
            ),  # 광고 → 필터됨
        ]


class WalmartCollector(BaseCollector):
    """
    Walmart 리뷰 수집
    상태: 비공식 크롤링 가능
    신뢰도: ★★★★ (실구매자)
    엔진타입: 1 (별점 + 텍스트)
    """
    name        = 'walmart'
    engine_type = 1
    available   = False  # 크롤링 구현 시 True

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)
        return []

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                "Bought this for my daughter. Works perfectly, stays cool.",
                score=5, source='walmart'
            ),
            self.format_review(
                "Not worth the price. Overheats after 1 hour.",
                score=2, source='walmart'
            ),
        ]


class TrustpilotCollector(BaseCollector):
    """
    Trustpilot 리뷰 수집
    상태: 공식 API 있음 (무료 플랜)
    신뢰도: ★★★★ (브랜드 신뢰도)
    엔진타입: 1 (별점 + 텍스트)
    """
    name        = 'trustpilot'
    engine_type = 1
    available   = False  # API 키 발급 시 True

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        # TODO: Trustpilot API 연결
        # https://documentation.trustpilot.com/
        return []

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                "Excellent brand. Product quality is consistent.",
                score=5, source='trustpilot'
            ),
        ]


# ===============================
# 엔진2 (텍스트형) - 텍스트만
# LLM이 감정 분석해서 수치화
# ===============================

class RedditCollector(BaseCollector):
    """
    Reddit 리뷰 수집
    상태: 공식 API ✅ 무료
    신뢰도: ★★★★★ (솔직한 경험담)
    엔진타입: 2 (텍스트만)

    핵심: "where did you get?" 댓글 = 진짜 후기
    """
    name        = 'reddit'
    engine_type = 2
    available   = bool(REDDIT_CLIENT_ID)

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        try:
            # Reddit API 토큰 획득
            token = self._get_token()
            if not token:
                return self._mock_data(keyword, count)

            # 서브레딧 검색
            subreddits = ['BuyItForLife', 'gadgets', 'technology',
                         'malelivingspace', 'Parenting', 'Frugal']
            reviews = []

            for sub in subreddits[:3]:
                posts = self._search_subreddit(token, sub, keyword, count=3)
                reviews.extend(posts)
                if len(reviews) >= count:
                    break

            return reviews[:count]

        except Exception as e:
            print(f'[Reddit 오류] {e}')
            return self._mock_data(keyword, count)

    def _get_token(self):
        """Reddit OAuth 토큰"""
        try:
            import base64
            creds = base64.b64encode(
                f'{REDDIT_CLIENT_ID}:{REDDIT_SECRET}'.encode()
            ).decode()
            req = urllib.request.Request(
                'https://www.reddit.com/api/v1/access_token',
                data=b'grant_type=client_credentials',
                headers={
                    'Authorization': f'Basic {creds}',
                    'User-Agent': 'DecisionEngine/1.0'
                },
                method='POST'
            )
            res = urllib.request.urlopen(req)
            data = json.loads(res.read().decode())
            return data.get('access_token')
        except:
            return None

    def _search_subreddit(self, token, subreddit, keyword, count=5):
        """서브레딧에서 키워드 검색"""
        try:
            query = urllib.parse.quote(keyword)
            url   = f'https://oauth.reddit.com/r/{subreddit}/search?q={query}&limit={count}&sort=relevance'
            req   = urllib.request.Request(url, headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': 'DecisionEngine/1.0'
            })
            res  = urllib.request.urlopen(req)
            data = json.loads(res.read().decode())

            reviews = []
            for post in data.get('data', {}).get('children', []):
                p    = post.get('data', {})
                text = p.get('selftext', '') or p.get('title', '')
                if text and len(text) > 20:
                    reviews.append(self.format_review(
                        text[:500], source=f'reddit/r/{subreddit}'
                    ))
            return reviews
        except:
            return []

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                f"Been using {keyword} for 6 months. Honestly the best purchase. "
                "No overheating issues, battery lasts all day.",
                source='reddit/r/BuyItForLife'
            ),
            self.format_review(
                f"I was skeptical about {keyword} but after buying it I can say "
                "the fan noise is acceptable. Not the quietest but manageable.",
                source='reddit/r/gadgets'
            ),
            self.format_review(
                f"Where did you get this? Is this worth it for the price?",
                source='reddit/r/Frugal'
            ),
        ]


class YouTubeCollector(BaseCollector):
    """
    YouTube 댓글 수집
    상태: 공식 API ✅ 무료 (하루 10,000 유닛)
    신뢰도: ★★★★ (내돈내산 영상 댓글)
    엔진타입: 2 (텍스트만)

    핵심: "honest review", "I bought this" 댓글
    """
    name        = 'youtube'
    engine_type = 2
    available   = bool(YOUTUBE_API_KEY)

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        try:
            # 영상 검색
            videos = self._search_videos(keyword, max_results=3)
            reviews = []

            for video_id in videos:
                comments = self._get_comments(video_id, max_results=5)
                reviews.extend(comments)
                if len(reviews) >= count:
                    break

            return reviews[:count]

        except Exception as e:
            print(f'[YouTube 오류] {e}')
            return self._mock_data(keyword, count)

    def _search_videos(self, keyword, max_results=3):
        """YouTube 영상 검색"""
        query = urllib.parse.quote(f'{keyword} honest review')
        url   = (
            f'https://www.googleapis.com/youtube/v3/search'
            f'?part=id&q={query}&type=video'
            f'&maxResults={max_results}&key={YOUTUBE_API_KEY}'
        )
        try:
            res  = urllib.request.urlopen(url)
            data = json.loads(res.read().decode())
            return [item['id']['videoId']
                    for item in data.get('items', [])]
        except:
            return []

    def _get_comments(self, video_id, max_results=10):
        """영상 댓글 수집"""
        url = (
            f'https://www.googleapis.com/youtube/v3/commentThreads'
            f'?part=snippet&videoId={video_id}'
            f'&maxResults={max_results}&key={YOUTUBE_API_KEY}'
        )
        try:
            res      = urllib.request.urlopen(url)
            data     = json.loads(res.read().decode())
            comments = []
            for item in data.get('items', []):
                text = item['snippet']['topLevelComment']['snippet']['textDisplay']
                comments.append(self.format_review(
                    text, source=f'youtube/{video_id}'
                ))
            return comments
        except:
            return []

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                "I bought this 2 months ago and it's been amazing. "
                "No heat problems at all, very quiet fan.",
                source='youtube/comments'
            ),
            self.format_review(
                "Honest review after 3 months: battery life could be better "
                "but overall I'm satisfied with the purchase.",
                source='youtube/comments'
            ),
        ]


class InstagramCollector(BaseCollector):
    """
    Instagram 댓글/캡션 수집
    상태: Apify 필요 (유료 $49/월)
    신뢰도: ★★★★ (진짜 사용자 경험)
    엔진타입: 2 (텍스트만)

    핵심 신호:
    - "where did you get?" → 진짜 구매 경험
    - "use my code" → 광고 → 제외
    - 해시태그: #honestreviw #notsponsored
    """
    name        = 'instagram'
    engine_type = 2
    available   = bool(APIFY_TOKEN)

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        try:
            # Apify Instagram Scraper
            # https://apify.com/apify/instagram-hashtag-scraper
            hashtags = self._keyword_to_hashtags(keyword)
            reviews  = []

            for hashtag in hashtags[:2]:
                posts = self._scrape_hashtag(hashtag, count=5)
                reviews.extend(posts)

            # 광고 필터링
            real_reviews = [r for r in reviews if not r['is_ad']]
            return real_reviews[:count]

        except Exception as e:
            print(f'[Instagram 오류] {e}')
            return self._mock_data(keyword, count)

    def _keyword_to_hashtags(self, keyword):
        """키워드 → 인스타 해시태그 변환"""
        base = keyword.lower().replace(' ', '')
        return [
            f'{base}review',
            f'{base}honest',
            f'my{base}',
            'notsponsored',
            'honestproductreview'
        ]

    def _scrape_hashtag(self, hashtag, count=5):
        """Apify로 해시태그 크롤링"""
        try:
            url = 'https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/runs'
            body = json.dumps({
                'hashtags': [hashtag],
                'resultsLimit': count
            }).encode()
            req = urllib.request.Request(
                f'{url}?token={APIFY_TOKEN}',
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            # 실제 구현 시 run 완료 대기 필요
            return []
        except:
            return []

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                "Not sponsored! I bought this myself and honestly love it. "
                "Where did you get yours? Mine is from Amazon.",
                source='instagram/hashtag'
            ),
            self.format_review(
                "use my code SAVE20 for 20% off!",
                source='instagram/hashtag'
            ),  # 광고 → 필터됨
            self.format_review(
                "Been using this for a month. The quality is amazing, "
                "no complaints at all.",
                source='instagram/hashtag'
            ),
        ]


class GoogleBlogCollector(BaseCollector):
    """
    Google 블로그/리뷰 수집
    상태: Custom Search API (무료 100건/일)
    신뢰도: ★★★ (블로그 후기)
    엔진타입: 2 (텍스트만)
    """
    name        = 'google_blog'
    engine_type = 2
    available   = False  # Google Custom Search API 키 필요

    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
    GOOGLE_CX      = os.environ.get('GOOGLE_CX', '')

    def collect(self, keyword, product_title='', count=10):
        if not self.available:
            return self._mock_data(keyword, count)

        try:
            query = urllib.parse.quote(f'{keyword} honest review site:reddit.com OR site:blogger.com')
            url   = (
                f'https://www.googleapis.com/customsearch/v1'
                f'?q={query}&key={self.GOOGLE_API_KEY}&cx={self.GOOGLE_CX}'
                f'&num={min(count, 10)}'
            )
            res  = urllib.request.urlopen(url)
            data = json.loads(res.read().decode())

            reviews = []
            for item in data.get('items', []):
                snippet = item.get('snippet', '')
                if snippet:
                    reviews.append(self.format_review(
                        snippet, source=f"google/{item.get('displayLink', '')}"
                    ))
            return reviews

        except Exception as e:
            print(f'[Google 오류] {e}')
            return self._mock_data(keyword, count)

    def _mock_data(self, keyword, count):
        return [
            self.format_review(
                f"I've been using {keyword} for 3 months now. "
                "My honest opinion: great build quality, runs cool.",
                source='google/blog'
            ),
        ]


# ===============================
# 장소 레이어 통합 관리자
# ===============================
class CollectorManager:
    """
    모든 수집 장소 관리
    - 켜고 끄기 가능
    - API 연결 여부 자동 감지
    - 출처 추적
    """

    def __init__(self):
        # 미국 중심 컬렉터 등록
        self.collectors = {
            # 엔진1 (구조형) - 별점 + 텍스트
            'amazon':      AmazonCollector(),
            'walmart':     WalmartCollector(),
            'trustpilot':  TrustpilotCollector(),

            # 엔진2 (텍스트형) - 텍스트만
            'reddit':      RedditCollector(),
            'youtube':     YouTubeCollector(),
            'instagram':   InstagramCollector(),
            'google_blog': GoogleBlogCollector(),
        }

        # 기본 활성화 (API 있는 곳)
        self.enabled = {
            'amazon':      True,   # mock 데이터로 테스트
            'walmart':     True,
            'trustpilot':  True,
            'reddit':      True,
            'youtube':     True,
            'instagram':   True,
            'google_blog': True,
        }

    def enable(self, name):
        """특정 장소 켜기"""
        if name in self.enabled:
            self.enabled[name] = True

    def disable(self, name):
        """특정 장소 끄기"""
        if name in self.enabled:
            self.enabled[name] = False

    def collect_all(self, keyword, product_title='', count_per_source=5):
        """
        활성화된 모든 장소에서 리뷰 수집
        광고 자동 필터링
        출처 추적
        """
        all_reviews = {
            'engine1': [],  # 구조형 (별점 있음)
            'engine2': [],  # 텍스트형 (별점 없음)
        }
        source_counts = {}

        for name, collector in self.collectors.items():
            if not self.enabled.get(name, False):
                continue

            try:
                reviews = collector.collect(
                    keyword, product_title, count=count_per_source
                )

                # 광고 필터링
                real_reviews = [r for r in reviews if not r['is_ad']]
                source_counts[name] = len(real_reviews)

                # 엔진 타입별 분류
                if collector.engine_type == 1:
                    all_reviews['engine1'].extend(real_reviews)
                else:
                    all_reviews['engine2'].extend(real_reviews)

                print(f"  [{name}] {len(real_reviews)}개 수집 (광고 {len(reviews)-len(real_reviews)}개 제외)")

            except Exception as e:
                print(f'  [{name}] 오류: {e}')
                source_counts[name] = 0

        all_reviews['source_counts'] = source_counts
        all_reviews['total'] = (
            len(all_reviews['engine1']) + len(all_reviews['engine2'])
        )

        return all_reviews

    def status(self):
        """현재 연결 상태 출력"""
        print("\n[수집 장소 상태]")
        print(f"{'장소':<15} {'엔진':<8} {'API':<8} {'활성':<6}")
        print("-" * 40)
        for name, collector in self.collectors.items():
            engine  = f"엔진{collector.engine_type}"
            api     = "✅" if collector.available else "⚠️mock"
            enabled = "ON" if self.enabled.get(name) else "OFF"
            print(f"{name:<15} {engine:<8} {api:<8} {enabled}")


# ===============================
# 테스트
# ===============================
if __name__ == '__main__':
    manager = CollectorManager()
    manager.status()

    print("\n[테스트] 'laptop no heat' 리뷰 수집")
    results = manager.collect_all('laptop no heat', count_per_source=3)

    print(f"\n총 수집: {results['total']}개")
    print(f"엔진1(구조형): {len(results['engine1'])}개")
    print(f"엔진2(텍스트형): {len(results['engine2'])}개")

    print("\n[엔진1 샘플]")
    for r in results['engine1'][:2]:
        print(f"  [{r['source']}] {r['text'][:60]}...")
        if r['score']:
            print(f"  별점: {r['score']}/5")

    print("\n[엔진2 샘플]")
    for r in results['engine2'][:2]:
        print(f"  [{r['source']}] {r['text'][:60]}...")
