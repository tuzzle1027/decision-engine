# ===============================
# 리뷰 역추적 엔진
# 동현님 설계 / 로드 구현
# ===============================
#
# 엔진1 (구조형): 별점 + 텍스트 → 수치
# 엔진2 (텍스트형): 텍스트만 → LLM 역추적 → 수치
# 통합: 엔진1×0.5 + 엔진2×0.5 → 최종 점수
#
# 역추적 원리:
# "No heat issues at all" → 발열 +1
# "Overheats after 1 hour" → 발열 -1
# → 사용자가 원했던 것: "발열 없는 노트북"
# ===============================

import re
import json
import os
import urllib.request

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')


# ===============================
# LLM 호출
# ===============================
def call_llm(prompt, system='', max_tokens=500):
    import json as json2
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    body = json2.dumps({
        'model': 'gpt-4o-mini',
        'max_tokens': max_tokens,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': prompt}
        ]
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body, headers=headers, method='POST'
    )
    try:
        res    = urllib.request.urlopen(req)
        result = json2.loads(res.read().decode('utf-8'))
        return result['choices'][0]['message']['content']
    except Exception as e:
        return f'[LLM 오류] {str(e)}'


# ===============================
# 엔진1: 구조형
# 별점 + 텍스트 → 수치
# Amazon, Walmart, Trustpilot
# ===============================
class Engine1:
    """
    구조형 역추적 엔진
    - 별점으로 기본 점수 계산
    - 텍스트로 키워드 점수 보정
    - LLM 없이도 작동 (가볍고 빠름)
    """

    # 긍정/부정 키워드 사전
    POSITIVE = [
        'great', 'excellent', 'amazing', 'love', 'perfect',
        'no heat', 'cool', 'quiet', 'fast', 'long battery',
        'worth it', 'recommend', 'best', 'works great'
    ]
    NEGATIVE = [
        'heat', 'hot', 'overheats', 'slow', 'loud', 'noisy',
        'short battery', 'not worth', 'disappointed', 'broken',
        'poor quality', 'returned', 'waste of money'
    ]

    def analyze(self, reviews, user_keyword):
        """
        리뷰 분석 → 키워드 점수 계산

        반환:
        {
            keyword_scores: {키워드: 점수},
            total_score: 종합점수,
            satisfied: [만족 포인트],
            disappointed: [실망 포인트],
            source_breakdown: {출처: 점수}
        }
        """
        keyword_scores  = {}
        total_score     = 0
        satisfied       = []
        disappointed    = []
        source_breakdown = {}

        for review in reviews:
            text   = review.get('text', '').lower()
            score  = review.get('score')  # 별점
            source = review.get('source', 'unknown')

            # 1. 별점 기반 점수
            if score is not None:
                star_score = (score - 3)  # 3점=0, 5점=+2, 1점=-2
                total_score += star_score

            # 2. 키워드 기반 점수
            for kw in self.POSITIVE:
                if kw in text:
                    keyword_scores[kw] = keyword_scores.get(kw, 0) + 1
                    total_score += 0.5
                    if kw not in satisfied:
                        satisfied.append(kw)

            for kw in self.NEGATIVE:
                if kw in text:
                    keyword_scores[kw] = keyword_scores.get(kw, 0) - 1
                    total_score -= 0.5
                    if kw not in disappointed:
                        disappointed.append(kw)

            # 3. 출처별 점수 추적
            source_breakdown[source] = source_breakdown.get(source, 0) + (
                1 if score and score >= 4 else -1 if score and score <= 2 else 0
            )

        return {
            'keyword_scores':   keyword_scores,
            'total_score':      round(total_score, 2),
            'satisfied':        satisfied[:5],
            'disappointed':     disappointed[:5],
            'source_breakdown': source_breakdown,
            'review_count':     len(reviews),
            'engine':           1
        }


# ===============================
# 엔진2: 텍스트형
# 텍스트만 → LLM 역추적 → 수치
# Reddit, YouTube, Instagram
# ===============================

ENGINE2_SYSTEM = """
You are a review reverse-trace expert.
Read the review and reverse-trace what the buyer wanted BEFORE purchasing.

Output JSON only (no other text):
{
  "original_need": "what this person wanted before buying (one line)",
  "keyword_scores": {
    "keyword1": 1,
    "keyword2": -1
  },
  "satisfied": ["point1", "point2"],
  "disappointed": ["point1", "point2"],
  "is_genuine": true
}

Score rules:
+1 = satisfied with this keyword
-1 = disappointed with this keyword
is_genuine = false if sounds like advertisement

Examples:
Review: "No heat issues at all after 3 months"
→ original_need: "laptop with no overheating"
→ keyword_scores: {"heat": 1, "durability": 1}

Review: "Overheats after 1 hour of use"
→ original_need: "cool running laptop"
→ keyword_scores: {"heat": -1}
"""

class Engine2:
    """
    텍스트형 역추적 엔진
    - LLM이 리뷰 읽고 구매 전 니즈 복원
    - 별점 없어도 작동
    - Reddit, YouTube, Instagram용
    """

    def analyze(self, reviews, user_keyword):
        """
        텍스트 리뷰 → LLM 역추적 → 수치

        반환: 엔진1과 동일한 구조
        """
        keyword_scores   = {}
        total_score      = 0
        satisfied        = []
        disappointed     = []
        source_breakdown = {}
        original_needs   = []

        for review in reviews:
            text   = review.get('text', '')
            source = review.get('source', 'unknown')

            if not text or len(text) < 20:
                continue

            # LLM 역추적
            trace = self._reverse_trace(text, user_keyword)

            if not trace.get('is_genuine', True):
                continue  # 광고성 내용 제외

            # 원래 니즈 수집
            need = trace.get('original_need', '')
            if need:
                original_needs.append(need)

            # 키워드 점수 합산
            for kw, sc in trace.get('keyword_scores', {}).items():
                keyword_scores[kw] = keyword_scores.get(kw, 0) + sc
                total_score += sc

            satisfied.extend(trace.get('satisfied', []))
            disappointed.extend(trace.get('disappointed', []))

            # 출처별 점수
            sc_sum = sum(trace.get('keyword_scores', {}).values())
            source_breakdown[source] = source_breakdown.get(source, 0) + sc_sum

        return {
            'keyword_scores':   keyword_scores,
            'total_score':      round(total_score, 2),
            'satisfied':        list(set(satisfied))[:5],
            'disappointed':     list(set(disappointed))[:5],
            'source_breakdown': source_breakdown,
            'original_needs':   original_needs[:3],
            'review_count':     len(reviews),
            'engine':           2
        }

    def _reverse_trace(self, text, user_keyword):
        """LLM으로 리뷰 역추적"""
        prompt = f"""
User is looking for: {user_keyword}

Review text:
{text[:400]}

Reverse-trace what this reviewer needed before buying.
Focus on aspects related to "{user_keyword}".
"""
        result = call_llm(prompt, system=ENGINE2_SYSTEM, max_tokens=300)

        try:
            clean = result.strip()
            if '```' in clean:
                clean = re.sub(r'```json|```', '', clean).strip()
            return json.loads(clean)
        except:
            return {
                'original_need': user_keyword,
                'keyword_scores': {},
                'satisfied': [],
                'disappointed': [],
                'is_genuine': True
            }


# ===============================
# 통합 엔진
# 엔진1 + 엔진2 → 최종 점수
# ===============================
class ReviewEngine:
    """
    엔진1 + 엔진2 통합
    최종 점수 = 엔진1×w1 + 엔진2×w2

    출처별 점수도 표시 → 사용자에게 보여줄 수 있음
    "이 점수는 Amazon+Reddit 후기 기반"
    """

    def __init__(self, weight1=0.5, weight2=0.5):
        self.engine1  = Engine1()
        self.engine2  = Engine2()
        self.weight1  = weight1  # 구조형 가중치
        self.weight2  = weight2  # 텍스트형 가중치

    def analyze(self, all_reviews, user_keyword):
        """
        수집된 모든 리뷰 통합 분석

        all_reviews: CollectorManager.collect_all() 결과
        {
            'engine1': [...],  # 구조형 리뷰
            'engine2': [...],  # 텍스트형 리뷰
        }
        """
        result1 = {'total_score': 0, 'review_count': 0,
                   'satisfied': [], 'disappointed': [], 'source_breakdown': {}}
        result2 = {'total_score': 0, 'review_count': 0,
                   'satisfied': [], 'disappointed': [], 'source_breakdown': {},
                   'original_needs': []}

        # 엔진1 분석 (구조형)
        if all_reviews.get('engine1'):
            print(f"  [엔진1] {len(all_reviews['engine1'])}개 분석 중...")
            result1 = self.engine1.analyze(
                all_reviews['engine1'], user_keyword
            )

        # 엔진2 분석 (텍스트형)
        if all_reviews.get('engine2'):
            print(f"  [엔진2] {len(all_reviews['engine2'])}개 분석 중...")
            result2 = self.engine2.analyze(
                all_reviews['engine2'], user_keyword
            )

        # 통합 점수 계산
        total = (
            result1['total_score'] * self.weight1 +
            result2['total_score'] * self.weight2
        )

        # 출처별 점수 병합
        all_sources = {}
        all_sources.update(result1.get('source_breakdown', {}))
        for src, sc in result2.get('source_breakdown', {}).items():
            all_sources[src] = all_sources.get(src, 0) + sc

        return {
            'total_score':    round(total, 2),
            'engine1_score':  result1['total_score'],
            'engine2_score':  result2['total_score'],
            'review_count':   (result1['review_count'] +
                               result2['review_count']),
            'satisfied':      list(set(
                result1.get('satisfied', []) +
                result2.get('satisfied', [])
            ))[:5],
            'disappointed':   list(set(
                result1.get('disappointed', []) +
                result2.get('disappointed', [])
            ))[:5],
            'original_needs': result2.get('original_needs', []),
            'source_breakdown': all_sources,
            'keyword_scores': {
                **result1.get('keyword_scores', {}),
                **result2.get('keyword_scores', {})
            }
        }

    def format_result_for_user(self, product_title, analysis):
        """
        사용자에게 보여줄 출처별 점수
        동현님 아이디어: 어디서 평점이 높고 낮은지 표시
        """
        lines = [f"[{product_title[:25]}]"]

        if analysis['source_breakdown']:
            lines.append("출처별 평가:")
            for src, sc in sorted(
                analysis['source_breakdown'].items(),
                key=lambda x: x[1], reverse=True
            ):
                bar = "+" * abs(int(sc)) if sc > 0 else "-" * abs(int(sc))
                lines.append(f"  {src:<25} {bar or '0'}")

        lines.append(f"종합점수: {analysis['total_score']}")
        lines.append(f"리뷰수: {analysis['review_count']}개")

        if analysis['satisfied']:
            lines.append(f"만족: {', '.join(analysis['satisfied'][:3])}")
        if analysis['disappointed']:
            lines.append(f"아쉬움: {', '.join(analysis['disappointed'][:3])}")

        return '\n'.join(lines)


# ===============================
# 테스트
# ===============================
if __name__ == '__main__':
    from review_collectors import CollectorManager

    print("리뷰 역추적 엔진 테스트")
    print("=" * 40)

    # 테스트 데이터
    manager = CollectorManager()
    reviews = manager.collect_all('laptop no heat', count_per_source=3)

    print(f"\n수집 완료: {reviews['total']}개")
    print(f"엔진1: {len(reviews['engine1'])}개")
    print(f"엔진2: {len(reviews['engine2'])}개")

    # 엔진 분석
    engine = ReviewEngine()
    result = engine.analyze(reviews, 'laptop no heat')

    print(f"\n[분석 결과]")
    print(f"종합 점수:  {result['total_score']}")
    print(f"엔진1 점수: {result['engine1_score']}")
    print(f"엔진2 점수: {result['engine2_score']}")
    print(f"만족:  {result['satisfied']}")
    print(f"아쉬움: {result['disappointed']}")

    print("\n[출처별 표시]")
    print(engine.format_result_for_user('Test Laptop Pro', result))
