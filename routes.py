# ===============================
# routes.py
# Flask 라우트 (Blueprint 방식)
# ===============================
import re

import os
import json
from flask import Blueprint, request, jsonify, send_from_directory, session

bp = Blueprint('routes', __name__)


# ★ 픽코 헌법 (영어 압축 ~50토큰, 처음 + 중요한 곳)
PICKO_IDENTITY = """You are Picko. A shopping critic on the user's side.
User is a first-time buyer solving a problem, not buying a product.
Explain with real-life situations, not specs.
Never: fake confidence, pushy recommendations, ad-style language, expensive-first bias."""

# ★ 픽코 리마인더 (~10토큰, 나머지)
PICKO_REMIND = "Remember: Picko. User's side. No fake confidence."

# ★ 괄호 안 쉼표 무시하고 분리
def _split_opts(text):
    result = []
    current = ''
    depth = 0
    for ch in text:
        if ch in ('(', '（'): depth += 1; current += ch
        elif ch in (')', '）'): depth -= 1; current += ch
        elif ch == ',' and depth == 0:
            if current.strip(): result.append(current.strip())
            current = ''
        else: current += ch
    if current.strip(): result.append(current.strip())
    return result

def _calc_sensor(text):
    """사용자 입력에서 의도 수치 계산 (0~1)"""
    s = {}
    if any(k in text for k in ['살까', '말까', '고민', '망설', '어떻게', '할까', '사야']):
        s['갈등'] = 0.9
    if any(k in text for k in ['비싸', '부담', '저렴', '가성비', '싸게', '가격', '돈이']):
        s['가격저항'] = 0.8
    if any(k in text for k in ['후회', '문제', '걱정', '실패', '잘못', '책임', '괜찮을까']):
        s['불안'] = 0.8
    if any(k in text for k in ['다른거', '비교', '더 좋은', '말고', '대신', 'vs', '어느게', '뭐가']):
        s['비교욕구'] = 0.7
    if any(k in text for k in ['좋은데', '맘에', '괜찮아', '마음에', '만족']):
        s['만족'] = 0.7
    if any(k in text for k in ['빨리', '급해', '오늘', '내일', '지금', '바로']):
        s['긴급'] = 0.8
    if any(k in text for k in ['단점', '약점', '문제점', '나쁜', '아쉬운']):
        s['단점탐색'] = 0.9
    if any(k in text for k in ['장점', '좋은점', '강점', '잘하는']):
        s['장점탐색'] = 0.9
    if any(k in text for k in ['짜증', '미쳐', '어이없', '말이되냐', '거참', '답답', '황당',
                                '화나', '열받', '실망', '뭐야 진짜', '진짜로', '도대체',
                                '씨', '존나', '개같', '미친', '뭐하는', '어떻게 하라고']):
        s['화남'] = 0.9
    return s


@bp.route('/chat_stream', methods=['POST'])
def chat_stream():
    """
    SSE 스트리밍 - 상황판 로딩 진행상황 실시간 표시!
    회색 → 먹색, 숫자 카운터 애니메이션
    """
    from flask import Response, stream_with_context
    import threading, queue, json, time

    data = request.json or {}
    user_input = data.get('message', '')
    sess = data.get('session') or {}

    # ★ 마음 상황판 정보를 user_context에 반영 (LLM이 항상 볼 수 있도록)
    _profile = sess.get('user_profile', {})
    if _profile:
        _pp = []
        for _pk, _pv in _profile.items():
            if str(_pk).startswith('_'): continue
            if isinstance(_pv, list) and _pv:
                _pp.append(', '.join([str(x) for x in _pv]))
            elif _pv:
                _pp.append(str(_pv))
        if _pp:
            _profile_text = '마음상황판: ' + ' / '.join(_pp)
            _existing = sess.get('user_context', '')
            if '마음상황판' not in _existing:
                sess['user_context'] = _profile_text + (' / ' + _existing if _existing else '')
            # ★ 네이버 검색에도 마음 전달
            from naver_api import set_mind_context
            set_mind_context(' '.join(_pp))
            print(f'[마음→네이버] {" ".join(_pp)}')

    # ★ 네/아니요 확인 대기 중
    YES_KEYWORDS = ['네', '예', '응', '그래', '좋아', '고고', 'ok', 'OK', '찾아줘', '바로', '해줘']
    NO_KEYWORDS = ['아니요', '아니', '괜찮아', '됐어', '노', 'no']

    if sess.get('awaiting_confirm'):
        if any(k in user_input for k in YES_KEYWORDS):
            original_input = sess.pop('awaiting_input', user_input)
            sess.pop('is_modify', None)
            sess.pop('awaiting_confirm', None)
            sess.pop('last_products', None)  # 맥락 판단 건너뛰고 바로 검색
            user_input = original_input
            print(f'[확인→검색] "{original_input[:20]}" → decision_engine')
        elif any(k in user_input for k in NO_KEYWORDS):
            sess.pop('awaiting_confirm', None)
            sess.pop('awaiting_input', None)
            def generate_no():
                yield f"data: {json.dumps({'type': 'empathy', 'msg': '알겠어요! 더 궁금한 게 있으면 언제든 물어보세요.'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': 'CONTEXT_REPLY', 'session': sess}, ensure_ascii=False)}\n\n"
            return Response(stream_with_context(generate_no()), mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})

    # ★ 맥락 대화 판단 - last_products 있으면 LLM에게 판단 맡기기
    last_products = sess.get('last_products', [])

    if last_products:
        from main import call_llm
        sensor = _calc_sensor(user_input)
        sensor_text = '\n'.join([f'{k}:{v}' for k, v in sensor.items()]) if sensor else '없음'
        print(f'[사용자반응] {sensor_text[:50]}')

        judge_prompt = f"""{PICKO_REMIND}

사용자가 쇼핑 중 메시지를 보냈어요.

방금 추천받은 제품: {', '.join([p['name'][:15] for p in last_products[:3]])}
사용자 상황: {sess.get('user_context', '')}
현재 선택 조건: {sess.get('selections', '')}
의도 센서: {sensor_text}

사용자 메시지: "{user_input}"

이 메시지가 다음 중 어느 것인지 판단해주세요:
A: 추천받은 제품에 대한 질문이나 대화 (단점, 장점, 비교, 살까말까, 맥락 확인 등)
B: 새로운 제품 검색 요청이지만 조건이 불충분 (소재나 인원수 등 빠진 조건 있음)
C: 대화 중 조건이 충분히 완성됨 (제품 종류 + 주요 조건 2개 이상 명확히 있음)
D: 기존 조건 수정 요청 (이거 빼고, 바꿔줘, 대신, 말고, 다시 등)

A, B, C, D 중 딱 한 글자만 답하세요."""

        judge = call_llm(judge_prompt, max_tokens=5).strip().upper()
        print(f'[맥락판단] "{user_input[:20]}" → {judge}')

        if judge == 'D':
            # 조건 수정 요청 → 수정 내용 확인 후 재검색
            modify_prompt = f"""
현재 조건: {sess.get('selections', '')}
사용자 수정 요청: {user_input}

수정된 조건을 한 줄로 요약하고 "이 조건으로 다시 찾아드릴까요?" 로 끝내주세요.
예: "스윙 기능으로 바꿔서 다시 찾아드릴까요?"
1문장만."""
            modify_msg = call_llm(modify_prompt, max_tokens=80).strip()
            sess['awaiting_confirm'] = True
            sess['awaiting_input'] = user_input
            sess['is_modify'] = True  # 수정 플래그

            def generate_modify():
                yield f"data: {json.dumps({'type': 'empathy', 'msg': modify_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': 'CONTEXT_REPLY', 'session': sess, 'show_confirm': True}, ensure_ascii=False)}\n\n"

            print(f'[조건수정감지] "{user_input[:20]}" → 수정 확인 요청')
            return Response(stream_with_context(generate_modify()), mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})

        elif judge == 'C':
            # 조건 완성 → 확인 후 바로 검색
            confirm_prompt = f"""
사용자 메시지: {user_input}
사용자 상황: {sess.get('user_context', '')}

사용자가 원하는 조건을 한 줄로 요약하고 "이 조건으로 찾아드릴까요?" 로 끝내주세요.
예: "3인용 가죽 베이지 소파로 찾아드릴까요?"
1문장만."""
            confirm_msg = call_llm(confirm_prompt, max_tokens=80).strip()
            sess['awaiting_confirm'] = True
            sess['awaiting_input'] = user_input

            def generate_confirm():
                yield f"data: {json.dumps({'type': 'empathy', 'msg': confirm_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': 'CONTEXT_REPLY', 'session': sess, 'show_confirm': True}, ensure_ascii=False)}\n\n"

            print(f'[조건완성감지] "{user_input[:20]}" → 확인 요청')
            return Response(stream_with_context(generate_confirm()), mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})

        elif judge == 'A':
            # 맥락 대화 처리
            user_context = sess.get('user_context', '')
            products_text = '\n'.join([
                f"{p['rank']}순위: {p['name']} / {p['price']}원 / "
                f"품질:{p.get('quality_pct', '?')}% / 만족:{p.get('satisfaction_pct', '?')}% / "
                f"센서:{p.get('sensor', '')} / "
                f"장점:{', '.join(p['pros'][:3])} / 단점:{', '.join(p['cons'][:3])}\n"
                f"  실제후기: {' | '.join(p.get('reviews', [])[:3])}"
                for p in last_products
            ])
            # 텍스트 + 수치 함께
            signal_tag = f' [{sensor_text}]' if sensor_text != '없음' else ''

            prompt = f"""{PICKO_REMIND}

사용자가 방금 추천받은 제품 3개를 보다가 말을 걸었어요.

사용자 상황: {user_context}

추천 제품 데이터:
{products_text}

사용자 메시지: "{user_input}"{signal_tag}

말투 규칙:
- "좋은 질문이에요" "말씀하신 것처럼" 같은 AI 클리셰 절대 금지
- "~할 것 같아요" "~일 수 있어요" 대신 솔직하게, 단 확신 과장 금지
- "꼭 이걸 사세요" 같은 단정적 추천 금지 → "후기 기반으로는 이게 나아요" 수준
- 출처 물어보면 실제후기 블로그 링크 있으면 언급하기
- 친구한테 솔직하게, 유머는 자연스럽게 한 번만, 이모지 1개 이하
- 3~4문장, 자연스러운 대화체

답변 규칙:
- 센서 수치 높은 감정에 집중 (갈등→결정도움, 불안→안심, 가격저항→가치설명)
- 비교욕구:0.7 이상이면 반드시 아래 형식으로 비교표 만들기:
  ─── A제품 vs B제품 ───
  
  A제품 (가격)
  ✅ 장점1
  ✅ 장점2
  ❌ 단점1
  
  B제품 (가격)
  ✅ 장점1
  ❌ 단점1
  
  👉 한 줄 결론
- 제품 데이터와 실제 후기 우선
- 소재·기능 일반 지식도 활용
- 데이터 없는 스펙·가격 만들어내기 금지
- 광고 금지, 상황판이나 새 추천 금지"""

            answer = call_llm(prompt, max_tokens=200).strip()

            def generate_context():
                # 출처 1개 선택 (가장 관련 있는 제품의 첫 번째 voice)
                source_voice = None
                for p in last_products:
                    voices = p.get('voices', [])
                    if voices and voices[0].get('url'):
                        source_voice = voices[0]
                        break
                yield f"data: {json.dumps({'type': 'empathy', 'msg': answer}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': 'CONTEXT_REPLY', 'session': sess, 'source_voice': source_voice}, ensure_ascii=False)}\n\n"

            print(f'[맥락대화] "{user_input[:20]}" → 대화 처리')
            return Response(
                stream_with_context(generate_context()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
            )

        else:
            # B: 새 검색 요청 → 먼저 답변 + 찾아드릴까요 제안
            user_context = sess.get('user_context', '')
            products_text = '\n'.join([p['name'][:20] for p in last_products])
            prompt = f"""{PICKO_REMIND}

사용자 상황: {user_context}
기존 추천 제품: {products_text}
사용자 메시지: {user_input}

규칙:
- 사용자 맥락(강아지, 아이 등) 기반으로 새 요청에 대해 간단히 코멘트
- 마지막에 반드시 "찾아드릴까요?" 로 끝내기
- 2~3문장, 대화체
- 상황판 절대 던지지 말것"""

            answer = call_llm(prompt, max_tokens=150).strip()
            sess['awaiting_confirm'] = True
            sess['awaiting_input'] = user_input  # 뭘 찾을지 기억

            def generate_suggest():
                yield f"data: {json.dumps({'type': 'empathy', 'msg': answer}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'response': 'CONTEXT_REPLY', 'session': sess, 'show_confirm': True}, ensure_ascii=False)}\n\n"

            print(f'[새검색제안] "{user_input[:20]}" → 답변+제안')
            return Response(
                stream_with_context(generate_suggest()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
            )

    result_queue = queue.Queue()

    def run_engine():
        from main import decision_engine
        try:
            result = decision_engine(user_input, sess)
            result_queue.put(('done', result, sess))
        except Exception as e:
            result_queue.put(('error', str(e), sess))

    thread = threading.Thread(target=run_engine, daemon=True)
    thread.start()

    def generate():
        # ★ 공감멘트 즉시 전송! LLM 없이! 빠와 동시에!
        raw_product = sess.get('raw_product', '')
        if not raw_product:
            # user_input에서 제품명 빠르게 추출
            PRODUCT_KEYWORDS = [
                '소파', '침대', '책상', '의자', '옷장', '러그',
                '세탁기', '냉장고', '에어컨', '청소기', '건조기',
                '독서대', '행거', '수납장', '거실장', '식탁',
            ]
            for p in PRODUCT_KEYWORDS:
                if p in user_input:
                    raw_product = p
                    break

        # 세션 맥락 기반 공감멘트 (즉시!)
        context_hint = ''
        if any(k in user_input for k in ['결혼', '신혼', '이사']):
            context_hint = '새 보금자리에 딱 맞는'
        elif any(k in user_input for k in ['아이', '아기', '육아']):
            context_hint = '아이와 함께 쓸'
        elif any(k in user_input for k in ['강아지', '고양이', '반려']):
            context_hint = '반려동물과 함께 할'

        if raw_product:
            if context_hint:
                empathy_msg = f'{context_hint} {raw_product}, 함께 찾아드릴게요! 😊'
            else:
                empathy_msg = f'{raw_product} 잘 찾아드릴게요! 😊'
            yield f"data: {json.dumps({'type': 'empathy', 'msg': empathy_msg}, ensure_ascii=False)}\n\n"

        # 단계별 진행 메시지
        steps = [
            (0.2, 'collect', '제품 데이터 분석 중'),
            (1.8, 'review',  '제품 옵션 확인 중'),
            (3.2, 'price',   '가격 구간 확인 중'),
        ]
        start = time.time()
        step_idx = 0

        while True:
            elapsed = time.time() - start

            # 단계 메시지 전송
            if step_idx < len(steps):
                t, key, msg = steps[step_idx]
                if elapsed >= t:
                    yield f"data: {json.dumps({'type': 'progress', 'key': key, 'msg': msg}, ensure_ascii=False)}\n\n"
                    step_idx += 1

            # 결과 확인
            try:
                event_type, result, updated_sess = result_queue.get_nowait()
                if event_type == 'done':
                    yield f"data: {json.dumps({'type': 'done', 'response': result, 'session': updated_sess}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'msg': result}, ensure_ascii=False)}\n\n"
                break
            except queue.Empty:
                pass

            time.sleep(0.1)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@bp.route('/chat', methods=['POST'])
def chat():
    from main import decision_engine
    from naver_api import set_mind_context
    data       = request.json or {}
    user_input = data.get('message', '')
    session    = data.get('session') or {}
    if not user_input:
        return jsonify({'error': 'message required'}), 400

    # ★ 마음 상황판 → 네이버 검색에 전달
    _profile = session.get('user_profile', {})
    if _profile:
        _pp = []
        for _pk, _pv in _profile.items():
            if str(_pk).startswith('_'): continue
            if isinstance(_pv, list) and _pv:
                _pp.extend([str(x) for x in _pv])
            elif _pv:
                _pp.append(str(_pv))
        set_mind_context(' '.join(_pp))
        print(f'[마음→네이버] {" ".join(_pp)}')

    result = decision_engine(user_input, session)
    return jsonify({'response': result, 'session': session})


@bp.route('/health', methods=['GET'])
def health():
    from main import VERSION
    return jsonify({'status': 'ok', 'version': VERSION})


@bp.route('/version', methods=['GET'])
def version():
    from main import VERSION
    return jsonify({'version': VERSION})


@bp.route('/desire_start', methods=['POST'])
def desire_start():
    from naver_api import _DESIRE_CACHE, search_desire_board_images
    data        = request.json
    sess        = data.get('session') or {}
    raw_product = sess.get('raw_product') or data.get('product', '소파')
    vs_material = sess.get('vs_material', '')
    product     = f'{vs_material} {raw_product}' if vs_material and vs_material not in raw_product else raw_product

    desire_sid = sess.get('_desire_sid', '')
    if desire_sid and desire_sid in _DESIRE_CACHE:
        cached = _DESIRE_CACHE[desire_sid]
        if cached.get('status') == 'done' and cached.get('images'):
            print(f'[desire_start] 캐시 히트! {len(cached["images"])}장 즉시 반환')
            _DESIRE_CACHE.pop(desire_sid, None)
            return jsonify({'status': 'done', 'images': cached['images'], 'set_stage': 'desire_board'})

    print(f'[desire_start] {product} 직접 생성 시작')
    images = search_desire_board_images(product, selections=sess.get("selections", ""))
    print(f'[desire_start] {product} → {len(images)}장 완료')

    # ★ 이미지 6개 미만이면 욕망보드 스킵!
    if len(images) < 6:
        print(f'[desire_start] 이미지 부족 ({len(images)}장) → 욕망보드 스킵!')
        return jsonify({
            'status': 'skip',
            'message': f'이 조건은 이미지가 부족해서 바로 추천해드릴게요! 🛋️',
            'set_stage': 'desire_skip'
        })

    return jsonify({'status': 'done', 'images': images, 'set_stage': 'desire_board'})


@bp.route('/desire_add_one', methods=['POST'])
def desire_add_one():
    from naver_api import search_naver_shopping_images, search_naver_images, verify_images_batch
    data          = request.json
    product       = data.get('product', '소파')
    selections    = data.get('selections', '')
    sess          = data.get('session') or {}
    vs_material   = sess.get('vs_material', '')
    existing_urls = set(data.get('existing_urls', []))

    keyword = product
    if vs_material and vs_material not in keyword:
        keyword = f'{vs_material} {keyword}'
    if selections:
        parts = [p for p in selections.replace('형태:', '').replace('색상:', '').replace('가격:', '').replace('상판크기:', '').split() if ':' not in p]
        if parts:
            keyword += ' ' + ' '.join(parts[:2])

    print(f'[desire_add_one] 검색어: {keyword}')

    results = search_naver_shopping_images(keyword, limit=10)
    if not results:
        results = search_naver_images(keyword, limit=10)

    new_results = [r for r in results if r['url'] not in existing_urls]
    for item in new_results:
        verified = verify_images_batch([item['url']], product)
        if verified and verified[0]:
            item['style'] = '추가'
            return jsonify({'image': item})

    return jsonify({'image': None})


@bp.route('/get_price_range', methods=['POST'])
def get_price_range_api():
    """
    선택된 조합으로 동적 가격 구간 반환
    소재 + 폭 + 구성 등 선택값 조합 → 네이버 검색 → 가격 구간
    """
    from naver_api import get_price_range_by_selections
    data     = request.json or {}
    product  = data.get('product', '')
    selections = data.get('selections', {})  # {'소재': '원목', '폭': '1600', ...}
    if not product:
        return jsonify({'error': 'product required'}), 400
    price_ranges = get_price_range_by_selections(product, selections)
    # 가격 계산 쿼리 session 저장 (역추적용!)
    try:
        _form = selections.get('형태', '') if isinstance(selections, dict) else ''
        _base_q = f'{_form} {product}'.strip() if _form and _form != '직선형' else product
        session['price_base_query'] = _base_q
    except:
        pass
    return jsonify({'price_ranges': price_ranges})


@bp.route('/price_grade_comment', methods=['POST'])
def price_grade_comment():
    """가격 등급 선택 시 LLM 맥락 설명 생성"""
    import os, json, urllib.request
    data = request.json or {}
    product = data.get("product", "")
    grade = data.get("grade", "")
    context = data.get("context", "")
    price_range = data.get("price_range", "")

    GRADE_BASE = {
        "저가":  "💚 알뜰한 선택이에요!",
        "중가":  "💛 가장 많이 선택하는 구간이에요!",
        "고가":  "❤️ 프리미엄 구간이에요!",
        "최고가": "💎 이 조합에서 가장 높은 구간이에요!",
    }

    # price_range: 프론트에서 동적 계산된 실제 가격 (LLM이 언급할 필요 없음)
    prompt = f"""사용자가 {product}를 찾고 있어요.
현재 선택한 옵션: {context}
선택한 가격 등급: {grade} (이 가격대의 실제 범위는 별도로 표시됨)

2문장으로만 출력하세요:
1줄: {grade} 구간에서 현재 선택 옵션({context})의 특징 한 줄
2줄: (줄바꿈 후) 실용적인 조언 한 마디

규칙:
- 가격 숫자(만원) 언급 절대 금지 (가격은 이미 별도 표시됨)
- 현재 선택한 옵션의 특징과 어울리는지만 설명
- 한국어, 친근하게, 짧게
- 다른 텍스트 없이 2문장만 출력"""

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST"
        )
        res = urllib.request.urlopen(req, timeout=10)
        result = json.loads(res.read())
        comment = GRADE_BASE.get(grade, "") + " " + result["content"][0]["text"].strip()
        return jsonify({"comment": comment})
    except Exception as e:
        print(f"[가격설명오류] {e}")
        return jsonify({"comment": GRADE_BASE.get(grade, "")})


@bp.route('/get_price_grade', methods=['POST'])
def get_price_grade_api():
    """제품 저가/중가/고가 기준 반환"""
    from naver_api import get_price_grade
    data = request.json or {}
    product = data.get('product', '')
    if not product:
        return jsonify({'error': 'product required'}), 400
    grade = get_price_grade(product)
    return jsonify({'grade': grade})




@bp.route('/test_blog_review', methods=['GET'])
def test_blog_review():
    """
    네이버 블로그 API로 후기 수집 테스트
    사용법: /test_blog_review?product=튜즐 리딩리딩
    """
    import json, urllib.request, urllib.parse, re, os

    product = request.args.get('product', '튜즐 리딩리딩')
    NAVER_CLIENT_ID     = os.environ.get('NAVER_CLIENT_ID', '')
    NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

    if not NAVER_CLIENT_ID:
        return jsonify({'error': 'NAVER_CLIENT_ID 없음'}), 500

    results = {}

    # ── 블로그 검색 ──
    for query in [f'{product} 후기', f'{product} 리뷰', f'{product}']:
        enc = urllib.parse.quote(query)
        url = f'https://openapi.naver.com/v1/search/blog.json?query={enc}&display=10&sort=sim'
        req = urllib.request.Request(url, headers={
            'X-Naver-Client-Id': NAVER_CLIENT_ID,
            'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
        })
        try:
            res = urllib.request.urlopen(req, timeout=5)
            data = json.loads(res.read())
            items = data.get('items', [])
            reviews = []
            for item in items:
                desc = re.sub(r'<[^>]+>', '', item.get('description', ''))
                title = re.sub(r'<[^>]+>', '', item.get('title', ''))
                if desc:
                    reviews.append({
                        'title': title,
                        'text': desc[:200],
                        'url': item.get('link', ''),
                        'bloggername': item.get('bloggername', ''),
                    })
            results[query] = {
                'count': len(reviews),
                'reviews': reviews[:3]  # 샘플 3개만
            }
        except Exception as e:
            results[query] = {'error': str(e)}

    return jsonify({
        'product': product,
        'total_queries': len(results),
        'results': results
    })

@bp.route('/', methods=['GET'])
def index():
    static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    return send_from_directory(static_folder, 'index.html')


@bp.route('/recommend_stream', methods=['POST'])
def recommend_stream():
    """
    픽코3 스트리밍 추천
    1순위 완성 → 즉시 전송 → 2순위 → 3순위
    글자 단위 타이핑 효과 포함
    """
    from flask import Response, stream_with_context
    import threading, queue, json, time

    data = request.json or {}
    sess         = data.get('session') or {}
    product_name = data.get('product_name', '') or sess.get('product_name', '') or sess.get('raw_product', '')
    selections   = data.get('selections', '') or sess.get('selections', '')
    extra        = data.get('extra', '') or sess.get('extra', '')

    card_queue = queue.Queue()

    def run_recommendation():
        from recommendation import make_recommendation
        try:
            make_recommendation(
                product_name, selections, extra,
                session=sess,
                card_queue=card_queue,
            )
        except Exception as e:
            card_queue.put({'type': 'error', 'msg': str(e)})

    thread = threading.Thread(target=run_recommendation, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                item = card_queue.get(timeout=60)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get('type') in ('done', 'error'):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'msg': '타임아웃'})}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@bp.route('/more_recommendations', methods=['POST'])
def more_recommendations():
    from recommendation import get_more_recommendations
    data = request.get_json() or {}
    grade = data.get('grade', '')
    cache_key = data.get('cache_key', '')  # 프론트에서 직접 전달
    if not cache_key or not grade:
        return jsonify({'error': '캐시 없음', 'products': []})
    result = get_more_recommendations(cache_key, grade, count=3)
    return jsonify(result)


# ★ 비교해드려요 API
@bp.route('/compare_product', methods=['POST'])
def compare_product():
    """
    두 제품 VS 카드 생성
    body: { product_a, product_b }
    """
    try:
        data = request.get_json() or {}
        product_a = data.get('product_a', '').strip()
        product_b = data.get('product_b', '').strip()

        if not product_a or not product_b:
            return jsonify({'error': '제품명 두 개 필요', 'result': None})

        from board_vs import generate_situation_cards, get_vs_response
        print(f'[비교요청] {product_a} vs {product_b}')

        cards = generate_situation_cards(product_a, product_b)
        if not cards:
            return jsonify({'error': '비교 카드 생성 실패', 'result': None})

        scenario_key = f'{product_a}|||{product_b}'
        result = get_vs_response(scenario_key, cards)
        print(f'[비교완료] {len(cards)}개 카드')
        return jsonify({'result': result})

    except Exception as e:
        print(f'[비교오류] {e}')
        return jsonify({'error': str(e), 'result': None})


@bp.route('/test_ohou', methods=['GET'])
def test_ohou():
    """
    오늘의집 리뷰 ScrapingBee로 가져오기
    Railway IP 차단 → ScrapingBee 한국 IP로 우회
    """
    import requests as req, json as _json, os
    from flask import Response

    production_id = request.args.get('id', '574524')
    api_key = os.environ.get('SCRAPINGBEE_API_KEY', '')

    if not api_key:
        return Response(_json.dumps({'error': 'SCRAPINGBEE_API_KEY 없음'}, ensure_ascii=False),
                        content_type='application/json; charset=utf-8')

    target = (
        f'https://store.ohou.se/api/goods/reviews'
        f'?page=1&productionId={production_id}&per=20&order=best&stars=&option='
    )

    try:
        r = req.get('https://app.scrapingbee.com/api/v1/', params={
            'api_key':       api_key,
            'url':           target,
            'render_js':     'false',
            'premium_proxy': 'true',
            'country_code':  'kr',
        }, timeout=30)

        result = {'scrapingbee_status': r.status_code, 'production_id': production_id}

        if r.status_code == 200:
            try:
                data = r.json()
                reviews = data.get('reviews', data.get('data', []))
                result['SUCCESS'] = True
                result['total']   = data.get('total', len(reviews))
                result['count']   = len(reviews)
                result['keys']    = list(data.keys())
                result['sample']  = reviews[:2] if reviews else '없음'
            except Exception:
                result['raw'] = r.text[:500]
        else:
            result['error'] = r.text[:300]

        return Response(_json.dumps(result, ensure_ascii=False, indent=2),
                        content_type='application/json; charset=utf-8')

    except Exception as e:
        return Response(_json.dumps({'error': str(e)}, ensure_ascii=False),
                        content_type='application/json; charset=utf-8')


@bp.route('/discover_vreview', methods=['GET'])
def discover_vreview():
    """
    vreview 자동 탐색 - 구글 검색 기반
    1. 구글에서 site:*.co.kr OR *.com "vreview" {keyword} 검색
    2. 발견된 사이트 HTML 방문 → mall_id + product_id 추출
    3. vreview API 호출 → 리뷰 바로 가져오기
    """
    import requests as req, json as _json, re, os, urllib.parse as _up
    from flask import Response

    keyword  = request.args.get('q', '소파')
    max_scan = int(request.args.get('max', '15'))

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    candidate_urls = []
    seen_domains   = set()
    unique_urls    = []

    import urllib.request as _ur

    NAVER_ID     = os.environ.get('NAVER_CLIENT_ID', '')
    NAVER_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

    def _add_url(u):
        """중복 도메인 제거 후 추가"""
        skip = ['naver.com', 'google.', 'youtube.', 'daum.', 'kakao.', 'instagram.', 'facebook.']
        if any(s in u for s in skip):
            return
        d = re.search(r'https?://([^/]+)', u)
        if d and d.group(1) not in seen_domains:
            seen_domains.add(d.group(1))
            unique_urls.append(u)

    # ── 소스 1: 네이버 블로그 검색 "브이리뷰 + 키워드" ──
    # 블로그 포스트 안에 실제 쇼핑몰 링크가 박혀있음
    blog_queries = [f'브이리뷰 {keyword}', f'vreview {keyword}', f'브이리뷰 후기 {keyword}']
    for bq in blog_queries:
        try:
            enc = _up.quote(bq)
            nr  = _ur.Request(f'https://openapi.naver.com/v1/search/blog.json?query={enc}&display=20&sort=sim')
            nr.add_header('X-Naver-Client-Id', NAVER_ID)
            nr.add_header('X-Naver-Client-Secret', NAVER_SECRET)
            with _ur.urlopen(nr, timeout=8) as resp:
                blog_items = _json.loads(resp.read().decode('utf-8')).get('items', [])

            for bi in blog_items:
                # 블로그 본문 링크에서 쇼핑몰 URL 추출
                desc = bi.get('description', '') + bi.get('link', '')
                urls = re.findall(r'https?://[\w\-\.]+\.(?:co\.kr|com|kr)/[\w\-/%.?=&]{5,80}', desc)
                for u in urls:
                    _add_url(u)

                # 블로그 포스트 자체 방문해서 링크 추출
                blog_link = bi.get('link', '')
                if 'blog.naver.com' in blog_link or 'tistory.com' in blog_link:
                    try:
                        rb = req.get(blog_link, headers=HEADERS, timeout=6)
                        shop_urls = re.findall(
                            r'https?://[\w\-\.]+\.(?:co\.kr|com|kr)/(?:goods|product|shop|store|p)/[\w\-/%.?=&]{3,60}',
                            rb.text
                        )
                        for u in shop_urls:
                            _add_url(u)
                    except:
                        pass

            print(f'[블로그검색] "{bq}" → 현재 {len(unique_urls)}개 URL 확보')
        except Exception as e:
            print(f'[블로그검색오류] {bq}: {e}')

    # ── 소스 2: 네이버 쇼핑 (자사몰 URL 필터링 완화) ──
    try:
        enc = _up.quote(keyword)
        nr  = _ur.Request(f'https://openapi.naver.com/v1/search/shop.json?query={enc}&display=30&sort=sim')
        nr.add_header('X-Naver-Client-Id', NAVER_ID)
        nr.add_header('X-Naver-Client-Secret', NAVER_SECRET)
        with _ur.urlopen(nr, timeout=8) as resp:
            shop_items = _json.loads(resp.read().decode('utf-8')).get('items', [])

        for si in shop_items:
            link = si.get('link', '')
            # 자사몰만: brand.naver.com 포함, search.shopping 제외
            if 'search.shopping.naver.com' in link:
                continue
            _add_url(link)

        print(f'[쇼핑검색] 네이버 쇼핑 → 현재 {len(unique_urls)}개 URL 확보')
    except Exception as e:
        print(f'[쇼핑검색오류] {e}')

    print(f'[탐색대상] 총 {len(unique_urls)}개 URL')

    # ── STEP 2: 각 URL 방문 → vreview 감지 → 리뷰 추출 ──
    results = []
    found   = []

    for url in unique_urls[:max_scan]:
        item = {
            'url': url[:80],
            'vreview': False,
            'mall_id': '',
            'product_id': '',
            'review_sample': None,
        }

        try:
            rp  = req.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
            html = rp.text
            final_url = rp.url
            domain = f'https://{final_url.split("/")[2]}'

            if 'vreview.tv' not in html and 'vreview' not in html.lower():
                results.append(item)
                continue

            item['vreview'] = True

            # mall_id 추출
            m_id = re.search(
                r'vrid[=\s"\':()+]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                html, re.IGNORECASE
            )
            mall_id = m_id.group(1) if m_id else ''
            item['mall_id'] = mall_id
            item['domain']  = domain

            # product_id 추출 (vreview 위젯 초기화 코드 우선)
            pid_patterns = [
                r'product[_\-]?(?:remote[_\-]?)?id["\s:=\'(]+([A-Z]?\d{4,})',
                r'productNo["\s:=\'(]+(\d{4,})',
                r'"product_no"\s*:\s*(\d{4,})',
                r'data-product[_\-]?id=["\']([A-Z]?\d{4,})',
                r'/goods/(\d{4,})',
                r'/products?/(\d{4,})',
                r'product_no=(\d{4,})',
                r'/p/(P\d+)',
            ]
            product_id  = ''
            search_text = final_url + html[:6000]
            for pat in pid_patterns:
                pm = re.search(pat, search_text, re.IGNORECASE)
                if pm:
                    product_id = pm.group(1)
                    break

            item['product_id'] = product_id

            # vreview API 호출
            if mall_id and product_id:
                rv = req.get(
                    f'https://one.vreview.tv/api/embed/v2/{mall_id}/reviews',
                    params={'offset': 0, 'limit': 3, 'product_remote_id': product_id, 'ordering': '-created_at'},
                    headers={'Origin': domain, 'Referer': final_url, 'Accept': 'application/json'},
                    timeout=8
                )
                item['review_api_status'] = rv.status_code
                if rv.status_code == 200:
                    data    = rv.json()
                    reviews = data.get('results', [])
                    item['review_sample'] = {
                        'total': data.get('count', 0),
                        'texts': [r.get('text', '')[:120] for r in reviews[:2]]
                    }
                    if reviews:
                        found.append(item)

        except Exception as e:
            item['error'] = str(e)[:80]

        results.append(item)
        print(f"[결과] {item['url'][:40]} → vreview={item['vreview']} mall_id={mall_id[:8] if mall_id else '없음'}")

    return Response(
        _json.dumps({
            'keyword':        keyword,
            'google_urls':    len(unique_urls),
            'scanned':        len(results),
            'vreview_found':  len([r for r in results if r['vreview']]),
            'reviews_fetched': len(found),
            'success':        found,
            'all_details':    results,
        }, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8'
    )


    import requests as req, json as _json, re, os, urllib.request as _ur, urllib.parse as _up
    from flask import Response

    keyword  = request.args.get('q', '소파')
    max_scan = int(request.args.get('max', '20'))

    NAVER_ID     = os.environ.get('NAVER_CLIENT_ID', '')
    NAVER_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }

    results  = []
    found    = []

    # ── STEP 1: 네이버 쇼핑 검색 ──
    try:
        enc = _up.quote(keyword)
        naver_url = f'https://openapi.naver.com/v1/search/shop.json?query={enc}&display={max_scan}&sort=sim'
        nr = _ur.Request(naver_url)
        nr.add_header('X-Naver-Client-Id', NAVER_ID)
        nr.add_header('X-Naver-Client-Secret', NAVER_SECRET)
        with _ur.urlopen(nr, timeout=8) as resp:
            naver_items = _json.loads(resp.read().decode('utf-8')).get('items', [])
    except Exception as e:
        return Response(_json.dumps({'error': f'네이버 검색 실패: {e}'}, ensure_ascii=False),
                        content_type='application/json; charset=utf-8')

    # ── STEP 2: 각 제품 페이지 방문 → vreview 감지 ──
    seen_malls = set()  # 중복 mall_id 방지

    for item in naver_items:
        link      = item.get('link', '')
        mall_name = item.get('mallName', '')
        title     = item.get('title', '')

        # 네이버 catalog/스마트스토어 제외 → 자사몰만
        if 'search.shopping.naver.com' in link:
            continue
        if 'smartstore.naver.com/main' in link:
            continue

        result_item = {
            'mall': mall_name,
            'title': re.sub(r'<[^>]+>', '', title)[:40],
            'link': link[:80],
            'vreview': False,
            'mall_id': '',
            'product_id': '',
            'review_sample': None,
        }

        try:
            rp = req.get(link, headers=HEADERS, timeout=8, allow_redirects=True)
            html     = rp.text
            final_url = rp.url

            # ── vreview 감지 ──
            if 'vreview.tv' not in html and 'vreview' not in html.lower():
                result_item['vreview'] = False
                results.append(result_item)
                continue

            result_item['vreview'] = True

            # ── mall_id 추출 (vrid= 패턴) ──
            m_mall = re.search(
                r'vrid[=\s"\':()+]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                html, re.IGNORECASE
            )
            if not m_mall:
                # 다른 패턴 시도
                m_mall = re.search(
                    r'mall[_\-]?id[=\s"\':()+]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                    html, re.IGNORECASE
                )

            mall_id = m_mall.group(1) if m_mall else ''
            result_item['mall_id'] = mall_id

            # 중복 mall 건너뜀
            if mall_id in seen_malls:
                results.append(result_item)
                continue
            if mall_id:
                seen_malls.add(mall_id)

            # ── product_id 추출 ──
            # 1순위: HTML에서 vreview 위젯 초기화 코드 안 product_id
            pid_patterns = [
                r'product[_\-]?(?:remote[_\-]?)?id["\s:=\'(]+([A-Z]?\d{4,})',
                r'productNo["\s:=\'(]+(\d{4,})',
                r'/goods/(\d{4,})',
                r'/products?/(\d{4,})',
                r'product_no=(\d{4,})',
                r'/p/(P\d+)',
                r'"product_no"\s*:\s*(\d{4,})',
                r'data-product[_\-]?id=["\']([A-Z]?\d{4,})',
            ]
            product_id = ''
            search_text = final_url + html[:5000]
            for pat in pid_patterns:
                pm = re.search(pat, search_text, re.IGNORECASE)
                if pm:
                    product_id = pm.group(1)
                    break

            result_item['product_id'] = product_id
            result_item['final_url']  = final_url[:100]

            # ── vreview API 호출 ──
            if mall_id and product_id:
                try:
                    base_url = f'https://{final_url.split("/")[2]}'
                    rv = req.get(
                        f'https://one.vreview.tv/api/embed/v2/{mall_id}/reviews',
                        params={'offset': 0, 'limit': 3, 'product_remote_id': product_id, 'ordering': '-created_at'},
                        headers={
                            'Origin': base_url,
                            'Referer': final_url,
                            'Accept': 'application/json',
                        },
                        timeout=8
                    )
                    result_item['review_api_status'] = rv.status_code
                    if rv.status_code == 200:
                        data = rv.json()
                        reviews = data.get('results', [])
                        result_item['review_sample'] = {
                            'total': data.get('count', 0),
                            'texts': [r.get('text', '')[:120] for r in reviews[:2]]
                        }
                        if reviews:
                            found.append(result_item)
                except Exception as e:
                    result_item['review_error'] = str(e)

        except Exception as e:
            result_item['error'] = str(e)

        results.append(result_item)
        print(f"[탐색] {mall_name} → vreview={result_item['vreview']} mall_id={mall_id[:8] if mall_id else '없음'} product_id={product_id}")

    summary = {
        'keyword': keyword,
        'scanned': len(results),
        'vreview_found': len([r for r in results if r['vreview']]),
        'reviews_fetched': len(found),
        'success': found,
        'all_details': results,
    }

    return Response(
        _json.dumps(summary, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8'
    )


@bp.route('/scan_vreview', methods=['GET'])
def scan_vreview():
    """
    가구 브랜드 vreview 자동 스캔
    1. 공식몰 HTML 가져오기
    2. vreview 설치 여부 감지 (vrid= 패턴)
    3. mall_id 자동 추출
    4. 제품 리뷰까지 바로 가져오기
    """
    import requests as req, json as _json, re
    from flask import Response

    BRANDS = [
        {'name': '마켓비',      'url': 'https://marketb.kr',              'search': '소파'},
        {'name': '몽제',        'url': 'https://monze.co.kr',             'search': '소파'},
        {'name': '잭슨카멜레온', 'url': 'https://jacksonchameleon.co.kr',  'search': '소파'},
        {'name': '누잠',        'url': 'https://nujam.co.kr',             'search': '매트리스'},
        {'name': '호무로',      'url': 'https://homuro.co.kr',            'search': '소파'},
        {'name': '데코뷰',      'url': 'https://decoview.co.kr',          'search': '소파'},
        {'name': '까사미아',    'url': 'https://www.casamia.co.kr',       'search': '소파'},
        {'name': '일룸',        'url': 'https://www.iloom.com',           'search': '책상'},
        {'name': '에이스침대',  'url': 'https://www.acebed.com',          'search': '침대'},
        {'name': '삼분의일',    'url': 'https://1room.co.kr',             'search': '매트리스'},
    ]

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }

    results = []

    for brand in BRANDS:
        item = {
            'brand': brand['name'],
            'url': brand['url'],
            'vreview': False,
            'mall_id': '',
            'product_id': '',
            'review_sample': None,
        }

        try:
            r = req.get(brand['url'], headers=HEADERS, timeout=8, allow_redirects=True)
            html = r.text

            # ── vreview 감지 ──
            if 'vreview.tv' in html or 'vreview' in html.lower():
                item['vreview'] = True

                # mall_id 추출 (vrid= 패턴)
                m = re.search(
                    r'vrid[=\s"\':]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                    html, re.IGNORECASE
                )
                if m:
                    item['mall_id'] = m.group(1)

                # mall_id 있으면 → Naver API로 제품 URL 찾기 → product_id 추출 → 리뷰
                if item['mall_id']:
                    try:
                        import urllib.request as _ur, urllib.parse as _up, os as _os
                        naver_id     = _os.environ.get('NAVER_CLIENT_ID', '')
                        naver_secret = _os.environ.get('NAVER_CLIENT_SECRET', '')

                        # Naver API로 브랜드+제품 검색
                        query = _up.quote(f"{brand['name']} {brand['search']}")
                        naver_url = f'https://openapi.naver.com/v1/search/shop.json?query={query}&display=20&sort=sim'
                        nr = _ur.Request(naver_url)
                        nr.add_header('X-Naver-Client-Id', naver_id)
                        nr.add_header('X-Naver-Client-Secret', naver_secret)

                        with _ur.urlopen(nr, timeout=8) as resp:
                            naver_items = __import__('json').loads(resp.read().decode('utf-8')).get('items', [])

                        # 브랜드 도메인 힌트로 공식몰 URL 필터링
                        domain_hint = brand['url'].replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
                        product_url = ''
                        for ni in naver_items:
                            link = ni.get('link', '')
                            mall = ni.get('mallName', '')
                            if domain_hint in link or brand['name'] in mall:
                                product_url = link
                                break

                        item['product_url'] = product_url[:100] if product_url else ''

                        if product_url:
                            # 공식몰 제품 페이지 접근 → product_id 추출
                            rp = req.get(product_url, headers=HEADERS, timeout=8, allow_redirects=True)
                            final_url = rp.url
                            search_text = final_url + rp.text[:3000]

                            # 카페24 패턴: /goods/숫자, /product/숫자, product_no=숫자
                            # 리바트 패턴: /p/P숫자
                            pid_patterns = [
                                r'/goods/(\d+)',
                                r'/products?/(\d+)',
                                r'product_no=(\d+)',
                                r'/p/(P\d+)',
                                r'productId["\s:=]+(\d+)',
                                r'"product_no"\s*:\s*(\d+)',
                            ]
                            product_id = ''
                            for pat in pid_patterns:
                                pm = re.search(pat, search_text)
                                if pm:
                                    product_id = pm.group(1)
                                    break

                            item['product_id'] = product_id

                            if product_id:
                                rv = req.get(
                                    f'https://one.vreview.tv/api/embed/v2/{item["mall_id"]}/reviews',
                                    params={'offset': 0, 'limit': 3, 'product_remote_id': product_id, 'ordering': '-created_at'},
                                    headers={
                                        'Origin': brand['url'],
                                        'Referer': brand['url'] + '/',
                                        'Accept': 'application/json',
                                    },
                                    timeout=8
                                )
                                item['review_status'] = rv.status_code
                                if rv.status_code == 200:
                                    data = rv.json()
                                    reviews = data.get('results', [])
                                    item['review_sample'] = {
                                        'total': data.get('count', 0),
                                        'texts': [rev.get('text', '')[:100] for rev in reviews[:2]]
                                    }
                    except Exception as e:
                        item['review_error'] = str(e)

        except Exception as e:
            item['error'] = str(e)

        results.append(item)
        print(f"[스캔] {brand['name']} → vreview={item['vreview']} mall_id={item['mall_id'][:8] if item['mall_id'] else '없음'}")

    found = [r for r in results if r['vreview']]
    summary = {
        'total_scanned': len(BRANDS),
        'vreview_found': len(found),
        'brands_with_vreview': [r['brand'] for r in found],
        'details': results
    }

    return Response(
        _json.dumps(summary, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8'
    )


# ★ ScrapingBee 테스트 API
@bp.route('/test_vreview', methods=['GET'])
def test_vreview():
    """
    vreview 리뷰 추출 테스트
    흐름:
    1. 제품명으로 네이버 검색
    2. 공식몰 URL만 골라내기 (hyundailivart.co.kr OR brand.naver.com/livart)
    3. URL에서 product_id 추출 (P200092739 패턴)
    4. 공식몰 HTML에서 mall_id 추출 (vrid= 패턴)
    5. vreview API 호출 → 리뷰 반환
    """
    import requests as req, json as _json, re, os
    from flask import Response

    product_name = request.args.get('q', '리바트 소파')
    result = {'query': product_name, 'steps': {}}

    NAVER_ID     = os.environ.get('NAVER_CLIENT_ID', '')
    NAVER_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

    # ── STEP 1: 네이버 검색 ──
    try:
        import urllib.request as _ur, urllib.parse as _up
        enc = _up.quote(product_name)
        url = f'https://openapi.naver.com/v1/search/shop.json?query={enc}&display=20&sort=sim'
        r = _ur.Request(url)
        r.add_header('X-Naver-Client-Id', NAVER_ID)
        r.add_header('X-Naver-Client-Secret', NAVER_SECRET)
        with _ur.urlopen(r, timeout=8) as resp:
            items = _json.loads(resp.read().decode('utf-8')).get('items', [])
        result['steps']['1_naver'] = {'total': len(items)}
    except Exception as e:
        return Response(_json.dumps({'error': f'네이버 검색 실패: {e}'}, ensure_ascii=False), content_type='application/json; charset=utf-8')

    # ── STEP 2: 공식몰 URL 골라내기 ──
    OFFICIAL_URL_HINTS  = ['hyundailivart.co.kr', 'brand.naver.com/livart']
    OFFICIAL_MALL_NAMES = ['현대리바트', '리바트', 'livart', 'LIVART']
    official_url = ''
    all_links = []

    for item in items:
        link     = item.get('link', '')
        mall     = item.get('mallName', '')
        all_links.append({'link': link[:80], 'mall': mall})

        # URL 힌트 OR mallName 힌트
        if any(hint in link for hint in OFFICIAL_URL_HINTS) or \
           any(name in mall for name in OFFICIAL_MALL_NAMES):
            official_url = link
            result['steps']['2_filter'] = {
                'official_url': official_url,
                'matched_mall': mall,
                'all_links_sample': all_links[:5],
            }
            break

    # 그래도 못찾으면 → 리바트 공식몰 직접 검색
    if not official_url:
        try:
            enc2 = _up.quote(product_name)
            direct_url = f'https://www.hyundailivart.co.kr/search?q={enc2}'
            r_direct = req.get(direct_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }, timeout=8)
            html_d = r_direct.text
            # 제품 URL 패턴 추출
            m_direct = re.search(r'href="(/p/(P\d+))"', html_d)
            if m_direct:
                official_url = 'https://www.hyundailivart.co.kr' + m_direct.group(1)
                result['steps']['2_filter'] = {
                    'official_url': official_url,
                    'matched_mall': '리바트 공식몰 직접검색',
                    'all_links_sample': all_links[:5],
                }
            else:
                result['steps']['2_filter'] = {
                    'official_url': '',
                    'error': '공식몰 URL 못찾음',
                    'all_links_sample': all_links[:5],
                }
                return Response(_json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
        except Exception as e:
            result['steps']['2_filter'] = {'error': f'직접검색 실패: {e}', 'all_links_sample': all_links[:5]}
            return Response(_json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

    # ── STEP 3: product_id 추출 ──
    product_id = ''
    for pattern in [r'/p/(P\d+)', r'products?[=/]([\d]+)', r'goodsNo=(\d+)', r'product_no=(\d+)']:
        m = re.search(pattern, official_url)
        if m:
            product_id = m.group(1)
            break

    result['steps']['3_product_id'] = {'product_id': product_id, 'from_url': official_url[:100]}

    if not product_id:
        result['steps']['3_product_id']['error'] = 'product_id 추출 실패'
        return Response(_json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

    # ── STEP 4: 공식몰 HTML에서 mall_id(vrid=) 추출 ──
    # brand.naver.com 이면 실제 공식몰 페이지로 리다이렉트 따라가기
    mall_id = 'e5bae7ba-09eb-467d-ba16-94497293d48e'  # 리바트 기본값
    try:
        r2 = req.get(official_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }, timeout=10, allow_redirects=True)
        html = r2.text
        final_url = r2.url

        m2 = re.search(r'vrid=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', html)
        if m2:
            mall_id = m2.group(1)
            result['steps']['4_mall_id'] = {'mall_id': mall_id, 'source': 'HTML 추출 ✅', 'final_url': final_url[:100]}
        else:
            result['steps']['4_mall_id'] = {'mall_id': mall_id, 'source': '기본값 사용', 'final_url': final_url[:100]}

        # product_id가 URL에 없었으면 최종 URL에서 재시도
        if not product_id or product_id.isdigit() is False:
            for pattern in [r'/p/(P\d+)', r'products?[=/](\d+)']:
                m3 = re.search(pattern, final_url)
                if m3:
                    product_id = m3.group(1)
                    result['steps']['3_product_id']['product_id_from_final'] = product_id
                    break

    except Exception as e:
        result['steps']['4_mall_id'] = {'error': str(e), 'mall_id': mall_id, 'source': '기본값'}

    # ── STEP 5: vreview API 호출 ──
    try:
        vreview_url = (
            f'https://one.vreview.tv/api/embed/v2/{mall_id}/reviews'
            f'?offset=0&limit=10&product_remote_id={product_id}&ordering=-created_at'
        )
        r3 = req.get(vreview_url, headers={
            'Origin': 'https://widget2.vreview.tv',
            'Referer': 'https://widget2.vreview.tv/',
            'Accept': 'application/json',
        }, timeout=8)

        result['steps']['5_vreview'] = {'status': r3.status_code, 'url': vreview_url}

        if r3.status_code == 200:
            data = r3.json()
            reviews = data.get('results', [])
            result['steps']['5_vreview']['SUCCESS'] = True
            result['steps']['5_vreview']['total'] = data.get('count', len(reviews))
            result['steps']['5_vreview']['reviews'] = [
                {'text': rv.get('text', '')[:150], 'rating': rv.get('rating', ''), 'date': rv.get('created_at', '')[:10]}
                for rv in reviews[:3]
            ]
        else:
            result['steps']['5_vreview']['body'] = r3.text[:200]

    except Exception as e:
        result['steps']['5_vreview'] = {'error': str(e)}

    return Response(
        _json.dumps(result, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8'
    )


@bp.route('/test_scrapingbee', methods=['GET'])
def test_scrapingbee():
    import os, requests as req, re
    from bs4 import BeautifulSoup

    api_key = os.environ.get('SCRAPINGBEE_API_KEY', '')
    if not api_key:
        return jsonify({'error': 'SCRAPINGBEE_API_KEY 없음!'}), 400

    url = 'https://store.hanssem.com/goods/737687'

    try:
        print(f'[ScrapingBee테스트] URL: {url}')
        import json as _json

        # 오늘의집 리뷰 API 테스트!
        url = 'https://store.ohou.se/api/goods/reviews?page=1&productionId=574524&per=5&order=best&stars=&option='
        r = req.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://store.ohou.se/goods/574524',
        }, timeout=8)

        data = r.json() if r.status_code == 200 else {}
        reviews = data.get('reviews', data.get('data', []))

        from flask import Response
        return Response(
            _json.dumps({
                'status': r.status_code,
                'keys': list(data.keys()) if data else [],
                'total': data.get('total', data.get('count', 0)),
                'count': len(reviews),
                'sample': str(reviews[0])[:200] if reviews else '없음',
            }, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        )
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')

        # JSON-LD에서 평점/리뷰수 추출
        rating_info = {}
        for script in soup.find_all('script', type='application/ld+json'):
            if script.string and 'aggregateRating' in script.string:
                try:
                    data = _json.loads(script.string)
                    if 'aggregateRating' in data:
                        rating_info = {
                            'rating': data['aggregateRating'].get('ratingValue'),
                            'count': data['aggregateRating'].get('reviewCount'),
                            'name': data.get('name', '')
                        }
                except:
                    pass

        # 리뷰 텍스트 추출 (탭 클릭 후)
        review_texts = []

        # 방법1: 리뷰 관련 클래스
        for tag in soup.find_all(class_=re.compile(
            r'review|Review|comment|후기|opinion|Opinion|content|Contents', re.I
        )):
            txt = tag.get_text(strip=True)
            if len(txt) > 20 and re.search(r'[가-힣]{5,}', txt):
                cls = ' '.join(tag.get('class', []))
                review_texts.append({'class': cls[:60], 'text': txt[:200]})

        # 방법2: p 태그 중 한글 20자 이상
        for tag in soup.find_all('p'):
            txt = tag.get_text(strip=True)
            if len(txt) > 20 and re.search(r'[가-힣]{10,}', txt):
                review_texts.append({'class': 'p_tag', 'text': txt[:200]})

        # 방법3: li 태그 중 한글 20자 이상
        for tag in soup.find_all('li'):
            txt = tag.get_text(strip=True)
            if 20 < len(txt) < 500 and re.search(r'[가-힣]{10,}', txt):
                review_texts.append({'class': 'li_tag', 'text': txt[:200]})

        return jsonify({
            'status': r.status_code,
            'html_length': len(html),
            'rating_info': rating_info,
            'review_texts': review_texts[:15],
        })

    except Exception as e:
        print(f'[ScrapingBee오류] {e}')
        return jsonify({'error': str(e)}), 500


# ── 마음 상황판: 멀티턴 통합 ──
@bp.route('/mind_chat', methods=['POST'])
def mind_chat():
    from main import call_llm
    data = request.json or {}
    product = data.get('product', '')
    step = data.get('step', 'q1')
    history = data.get('history', '')

    if step == 'q1':
        # ★ 네이버 200개 → 코드로 빈도 분석!
        freq_text = ''
        try:
            from naver_api import fetch_titles_for_mind, analyze_mind_keywords
            _titles = fetch_titles_for_mind(product)
            if _titles:
                freq_text = analyze_mind_keywords(_titles, product)
        except Exception as e:
            print(f'[마음Q1오류] {e}')

        prompt = f"""{PICKO_IDENTITY}

Product: "{product}"

너는 이 제품 파는 가게 사장이야.
손님이 "{product} 필요해요" 라고 왔어.

아래는 네이버에서 실제로 많이 팔리는 키워드 빈도야:
{freq_text if freq_text else '(빈도 데이터 없음)'}

이 빈도를 참고해서 답 5가지를 만들어.
괄호 안에 구체적 행동 2~3개.

형식:
Q1: {product}이 필요한 이유가 뭔가요?
O1: 답1(행동, 행동), 답2(행동, 행동), 답3(행동, 행동), 답4(행동, 행동), 답5(행동, 행동)

★ 규칙:
- 각 15글자 이내
- 비슷한 것 합치기
- 전문 용어를 생활 언어로!
- 소재/스펙은 넣지 마 (패브릭, i7 등은 3구역에서)
- 예산 금지. 마크다운 금지. 한 줄에 콤마로. 다른 말 하지마."""

    elif step == 'q2map':
        opts_text = history  # Q1 선택지들
        prompt = f"""{PICKO_REMIND}

Product: {product}
Q1 선택지: {opts_text}

각 선택지별로 실제 사용 환경 질문 1개와 선택지 3개를 만들어.

형식:
[A] 질문
답: 선택1, 선택2, 선택3
[B] 질문
답: 선택1, 선택2, 선택3
[C] 질문
답: 선택1, 선택2, 선택3
[D] 질문
답: 선택1, 선택2, 선택3

규칙: 실제 사용 환경만! 보관/관리/청소 금지. 마크다운 금지. 다른 말 하지마."""

    elif step == 'q2':
        prompt = f"""{PICKO_REMIND}

{history}

위 대화를 보고 사용자가 선택한 유형에 맞는 실제 사용 환경/상황 질문 1개와 선택지 3~4개를 만들어.

★ 규칙: 실제로 이 제품을 사용하는 환경만 물어봐.
보관, 관리, 청소, 수리 같은 후처리 질문 금지!

형식:
Q2: 질문
O2: 선택지1, 선택지2, 선택지3

마크다운 금지. 다른 말 하지마."""

    elif step == 'q3':
        prompt = f"""{PICKO_REMIND}

{history}

위 대화를 보고, 이 사람이 {product} 쓸 때 "이것만은 싫다!" 하는 것을 질문으로 만들어.
걱정이 아니라 싫은 것! 싫은 것의 반대가 원하는 스펙이 됨.

형식:
Q3: {product} 쓸 때 이것만은 싫다! 하는 거 있으세요?
O3: 싫은것1, 싫은것2, 싫은것3, 싫은것4
M3: true

마크다운 금지. 다른 말 하지마."""

    elif step == 'concerns':
        prompt = f"""{PICKO_REMIND}

{history}

위 대화를 보고 이 사용자가 가장 걱정할 고민 5개를 키워드(2~4글자)로 만들고,
이 사람 상황에 맞는 직접입력 예시 문장 1개도 만들어줘.

형식:
키워드: 키워드1, 키워드2, 키워드3, 키워드4, 키워드5
예시: 예시 문장

마크다운 금지. 다른 말 하지마."""
    else:
        return jsonify({'error': 'unknown step'}), 400

    try:
        _max_tok = 300 if step == 'q1' else 200
        result = call_llm(prompt, max_tokens=_max_tok).strip()
        result = re.sub(r'#{1,3}\s*', '', result).replace('**', '').replace('---', '')
        lines = result.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            if line.startswith('- '):
                if cleaned: cleaned[-1] = cleaned[-1] + ', ' + line[2:].strip()
                else: cleaned.append(line[2:].strip())
            elif line: cleaned.append(line)
        result = '\n'.join(cleaned)
        print(f'[마음멀티턴] step={step} → {result[:150]}')

        parsed = {}

        # q2map 전용 파싱
        if step == 'q2map':
            opts_list = _split_opts(history)
            q2_map = {}
            current_key = ''
            for line in result.split('\n'):
                line = line.strip()
                if line.startswith('[') and ']' in line:
                    tag = line[1].upper()
                    rest = line[line.index(']')+1:].strip()
                    idx = ord(tag) - ord('A')
                    if 0 <= idx < len(opts_list):
                        current_key = opts_list[idx]
                        q2_map[current_key] = {'q': rest, 'opts': []}
                elif (line.startswith('답:') or line.startswith('O2')) and current_key:
                    q2_map[current_key]['opts'] = _split_opts(line.split(':',1)[1])
            parsed['q2_map'] = q2_map
            for k, v in q2_map.items():
                print(f'  Q2[{k[:10]}]: {v["q"][:30]} → {v["opts"]}')
            parsed['raw'] = result
            return jsonify(parsed)

        for line in result.split('\n'):
            line = line.strip()
            if not line: continue
            if line.startswith(('Q1:','Q2:','Q3:')): parsed['q'] = line.split(':',1)[1].strip()
            elif line.startswith(('O1:','O2:','O3:')):
                opts = _split_opts(line.split(':',1)[1])
                # ★ O2: O3: O4: O5: 접두어 제거
                cleaned_opts = []
                for o in opts:
                    o = re.sub(r'^O\d+:\s*', '', o).strip()
                    if o: cleaned_opts.append(o)
                parsed['opts'] = cleaned_opts
            elif line.startswith('M3:'): parsed['multi'] = True
            elif '키워드' in line:
                parts = line.split(':',1)
                if len(parts) > 1: parsed['concerns'] = [k.strip() for k in parts[1].split(',') if k.strip()]
            elif '예시' in line:
                parts = line.split(':',1)
                if len(parts) > 1: parsed['example'] = parts[1].strip()
        parsed['raw'] = result
        return jsonify(parsed)
    except Exception as e:
        print(f'[마음멀티턴오류] step={step}: {e}')
        return jsonify({'error': str(e)}), 500


# ── 마음 상황판: Q2 생성 (Q1 답변 기반) ──
@bp.route('/generate_q2', methods=['POST'])
def generate_q2():
    from main import call_llm
    data = request.json or {}
    product = data.get('product', '')
    q1_answer = data.get('q1_answer', '')

    prompt = f"""{PICKO_REMIND}

Product: {product}
User type: {q1_answer}

이 사람이 {product}을 사용할 환경/상황을 물어보는 질문 1개와 선택지 3~4개를 만들어.

형식:
Q2: 질문
O2: 선택지1, 선택지2, 선택지3

마크다운 금지. 다른 말 하지마."""

    try:
        result = call_llm(prompt, max_tokens=80).strip()
        result = re.sub(r'#{1,3}\s*', '', result).replace('**', '')
        q2 = {'q': '', 'opts': []}
        for line in result.split('\n'):
            line = line.strip()
            if line.startswith('Q2:'):
                q2['q'] = line.split(':',1)[1].strip()
            elif line.startswith('O2:'):
                q2['opts'] = _split_opts(line.split(':',1)[1])
        if not q2['opts']:
            q2 = {'q': f'{product} 주로 어디서 사용하세요?', 'opts': ['집', '야외', '사무실']}
        print(f'[마음Q2] {q1_answer} → {q2["q"]} → {q2["opts"]}')
        return jsonify({'q2': q2})
    except Exception as e:
        print(f'[마음Q2오류] {e}')
        return jsonify({'q2': {'q': f'{product} 주로 어디서 사용하세요?', 'opts': ['집', '야외', '사무실']}})


# ── 마음 상황판: Q3 생성 (Q1+Q2 답변 기반) ──
@bp.route('/generate_q3', methods=['POST'])
def generate_q3():
    from main import call_llm
    data = request.json or {}
    product = data.get('product', '')
    q1_answer = data.get('q1_answer', '')
    q2_answer = data.get('q2_answer', '')

    prompt = f"""{PICKO_REMIND}

Product: {product}
User: {q1_answer}, {q2_answer}

이 사람이 {product} 선택할 때 가장 걱정되는 부분을 질문으로 만들어.
이 사람 상황({q1_answer}, {q2_answer})에 맞는 걱정만!

형식:
Q3: {product} 선택할 때 가장 걱정되는 부분이요?
O3: 걱정1, 걱정2, 걱정3, 걱정4
M3: true

다른 말 하지마."""

    try:
        result = call_llm(prompt, max_tokens=80).strip()
        q3 = {'q': '', 'opts': [], 'multi': True}
        for line in result.split('\n'):
            line = line.strip()
            if line.startswith('Q3:'):
                q3['q'] = line.split(':',1)[1].strip()
            elif line.startswith('O3:'):
                q3['opts'] = _split_opts(line.split(':',1)[1])
        print(f'[마음Q3] {q1_answer}/{q2_answer} → {q3["opts"]}')
        return jsonify({'q3': q3})
    except Exception as e:
        print(f'[마음Q3오류] {e}')
        return jsonify({'q3': {'q': f'{product} 선택할 때 걱정되는 부분이요?', 'opts': ['가격', '품질', '내구성', 'AS'], 'multi': True}})


# ── 마음 상황판: 고민 키워드 생성 ──
@bp.route('/generate_concerns', methods=['POST'])
def generate_concerns():
    from main import call_llm
    data = request.json or {}
    product = data.get('product', '')
    profile = data.get('profile', {})

    # 마음 상황판 답변 전체를 문자열로 합치기 (키가 LLM 생성 질문이라 동적)
    profile_parts = []
    for k, v in profile.items():
        if str(k).startswith('_'): continue
        if isinstance(v, list) and v:
            profile_parts.append(', '.join([str(x) for x in v]))
        elif v:
            profile_parts.append(str(v))
    profile_text = ' / '.join(profile_parts) if profile_parts else '정보 없음'

    prompt = f"""{PICKO_IDENTITY}

Product: {product}
User info: {profile_text}

이 사람이 이 제품을 살 때 가장 걱정할 고민 5개를 짧은 키워드(2~4글자)로 만들고,
이 사람 상황에 맞는 직접입력 예시 문장 1개도 만들어줘.

형식:
키워드: 오염관리, 내구성, 발톱, 냄새, 가격
예시: 강아지가 소파를 긁어서 걱정돼요

반드시 위 형식으로만 답해. 다른 말 하지마."""

    try:
        result = call_llm(prompt, max_tokens=80).strip()
        keywords = []
        example = ''
        for line in result.split('\n'):
            line = line.strip()
            if '키워드' in line:
                parts = line.split(':',1)
                if len(parts) > 1:
                    keywords = [k.strip() for k in parts[1].split(',')][:5]
            elif '예시' in line:
                parts = line.split(':',1)
                if len(parts) > 1:
                    example = parts[1].strip()
        if not keywords:
            keywords = [k.strip() for k in result.split(',')][:5]
        print(f'[마음상황판] {product} / {profile_text} → {keywords} / 예시: {example}')
        return jsonify({'concerns': keywords, 'example': example})
    except Exception as e:
        print(f'[마음상황판오류] {e}')
        return jsonify({'concerns': ['가격', '내구성', '관리', '배송', '디자인']})


# ── 마음 상황판: 질문 3개 LLM 생성 ──
@bp.route('/generate_quick_questions', methods=['POST'])
def generate_quick_questions():
    from main import call_llm
    data = request.json or {}
    product = data.get('product', '')

    prompt = f"""{PICKO_IDENTITY}

Product: "{product}"

이 제품을 사려는 사람의 유형 4개를 만들어줘.
각 유형에 괄호로 구체적 용도 3~5개 상세히 적어.

형식:
Q1: 이 {product}은 주로 누가 사용하세요?
O1: 유형1(용도, 용도, 용도), 유형2(용도, 용도, 용도), 유형3(용도, 용도, 용도), 유형4(용도, 용도, 용도)

★ 규칙:
- "본인" 넣지 마. 사용자 유형+용도로만
- 예산/가격 금지
- 마크다운 금지
- 반드시 한 줄에 콤마로 구분
- 다른 말 하지마"""

    try:
        result = call_llm(prompt, max_tokens=200).strip()
        result = re.sub(r'#{1,3}\s*', '', result)
        result = result.replace('**', '').replace('---', '')
        # 리스트 변환
        lines = result.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            if line.startswith('- '):
                if cleaned:
                    cleaned[-1] = cleaned[-1] + ', ' + line[2:].strip()
                else:
                    cleaned.append(line[2:].strip())
            elif line:
                cleaned.append(line)
        result = '\n'.join(cleaned)
        print(f'[마음Q1정리] {result[:200]}')

        q1 = {'q': '', 'opts': []}
        for line in result.split('\n'):
            line = line.strip()
            if not line: continue
            if line.startswith('Q1:'):
                q1['q'] = line.split(':',1)[1].strip()
            elif line.startswith('O1:'):
                q1['opts'] = _split_opts(line.split(':',1)[1])

        if not q1['opts']:
            print(f'[마음Q1] 파싱 실패 → fallback')
            return jsonify({
                'q1': {'q': f'이 {product}은 주로 누가 사용하세요?', 'opts': ['본인(개인용)', '가족(공용)', '선물(타인용)']},
                'q2_map': {}
            })

        print(f'[마음Q1] {q1["q"]} → {q1["opts"]}')

        # ★ Q2는 미리 안 만듦 → 사용자 Q1 선택 후 따로 생성
        return jsonify({'q1': q1, 'q2_map': {}})
    except Exception as e:
        print(f'[마음상황판질문오류] {e}')
        return jsonify({
            'q1': {'q': f'이 {product}은 주로 누가 사용하세요?', 'opts': ['본인(개인용)', '가족(공용)', '선물(타인용)']},
            'q2_map': {}
        })
