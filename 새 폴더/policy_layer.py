# ===============================
# policy_layer.py
# 신호등 규칙
# 동현님 설계 / 로드 구현
# ===============================
#
# 역할:
# 센서 수치를 받아서
# LLM에게 어떻게 행동할지 지시
# 판단은 수치 기반, 표현은 LLM
# ===============================

def get_policy(scores):
    """
    센서 수치 → 정책 결정
    
    반환:
    {
        'action':  무엇을 할지,
        'rule':    LLM에 전달할 규칙,
        'reason':  이유
    }
    """
    S_type    = scores.get('S_type', 'S1')
    I_hat     = scores.get('I_hat', 0)
    Conflict  = scores.get('Conflict', 0)
    As        = scores.get('As', 0)
    res_state = scores.get('res_state', 'INTENT')
    constraint_interventions = scores.get('constraint_interventions', [])

    # ── 제약 경고 최우선 ──
    if constraint_interventions:
        top = constraint_interventions[0]
        return {
            'action': 'CONSTRAINT_WARNING',
            'reason': f"제약 위험 감지: {top['constraint']} R={top['R']}",
            'rule': f"""
⚠️ 제약 경고 먼저 출력하세요.
위험 항목: {top['constraint']}
경고 후 계속 대화를 이어가세요.
광고성 표현 금지.
"""
        }

    # ── 반의도 높음 → 보류 허용 ──
    if As >= 0.70:
        return {
            'action': 'ANTI_HIGH',
            'reason': f"반의도 높음 As={As}",
            'rule': """
사용자가 망설이고 있습니다.
"지금 당장 결정 안 하셔도 됩니다." 로 시작하세요.
부드럽게 핵심 질문 1개만 하세요.
절대 밀어붙이지 마세요.
"""
        }

    # ── 저항 상태 → 브레이크 ──
    if res_state == 'RESISTANCE':
        return {
            'action': 'RESISTANCE',
            'reason': f"저항 감지 Speed 낮음",
            'rule': """
사용자가 저항하고 있습니다.
공감 1줄 먼저.
조건을 좁히는 질문 1개만 하세요.
추천 절대 금지.
"""
        }

    # ── 반의도 상태 → 탐색 ──
    if res_state == 'ANTI_INTENT':
        return {
            'action': 'ANTI_INTENT',
            'reason': "반의도 감지",
            'rule': """
사용자가 반대 방향으로 가고 있습니다.
현재 상태 확인 질문 1개만 하세요.
추천 절대 금지.
"""
        }

    # ── 갈등 높음 → 6축 질문 ──
    if Conflict >= 2:
        top_axes = scores.get('top_axes', [])
        axes_str = ', '.join([a[0] for a in top_axes])
        drive    = scores.get('Drive', {})
        psi_mode = drive.get('Psi', False)
        return {
            'action': 'CONFLICT',
            'reason': f"갈등 {Conflict}개 감지: {axes_str}",
            'rule': f"""
갈등이 감지됐습니다. 핵심 갈등: {axes_str}
{'감성적으로 공감하고' if psi_mode else '명확하게 공감하고'} 핵심 질문 2~3개 하세요.
추천 절대 금지.
"""
        }

    # ── S2 + 의도 활성 → 상황판 ──
    if S_type == 'S2' and I_hat > 0 and Conflict == 0:
        return {
            'action': 'SITUATION_BOARD',
            'reason': f"S2 I_hat={I_hat} 의도 활성",
            'rule': """
반드시 상황판을 출력하세요. 역질문 절대 금지.
형식:
[A 속성명] A1 / A2 / A3
[B 속성명] B1 / B2 / B3
[C 속성명] C1 / C2 / C3
[D 직접입력] 원하는 조건을 직접 입력하세요
"""
        }

    # ── 기본 → 상황판 바로 진입 ──
    # 공산품 확인됐으면 역질문 필요 없음
    return {
        'action': 'SITUATION_BOARD',
        'reason': f"공산품 확인 → 상황판 바로 진입",
        'rule': """
반드시 상황판을 출력하세요. 역질문 절대 금지.
형식:
[A 속성명] A1 / A2 / A3
[B 속성명] B1 / B2 / B3
[C 속성명] C1 / C2 / C3
[D 직접입력] 원하는 조건을 직접 입력하세요
"""
    }


def build_llm_prompt(raw_text, scores, policy, review_result=None):
    """
    LLM에 전달할 최종 프롬프트 조립
    수치 + 정책 + 원문 + 리뷰 결과
    """
    drive     = scores.get('Drive', {})
    drive_str = (f"N={drive.get('N')} / W={drive.get('W')} / "
                 f"Ψ={drive.get('Psi')} / 주도={drive.get('dominant')}")

    # 리뷰 역추적 결과 있으면 추가
    review_str = ''
    if review_result and isinstance(review_result, dict):
        top3 = review_result.get('top3', [])
        if top3:
            review_str = '\n[리뷰 역추적 결과]\n'
            for i, item in enumerate(top3, 1):
                p = item.get('product', {})
                review_str += (
                    f"{i}. {p.get('title','')[:30]}\n"
                    f"   점수: {item.get('total_score',0)} | "
                    f"리뷰: {item.get('review_count',0)}개\n"
                    f"   만족: {', '.join(item.get('satisfied',[])[:2]) or '없음'}\n"
                    f"   아쉬움: {', '.join(item.get('disappointed',[])[:2]) or '없음'}\n"
                    f"   링크: {p.get('link','')}\n"
                )

    prompt = f"""
[수치 - 판단 기준]
S_type:   {scores.get('S_type')} (S1=탐색 / S2=의도명시)
I_hat:    {scores.get('I_hat')} [활성: {scores.get('activated')}]
R:        {scores.get('R')}
Phi:      {scores.get('Phi')}
As:       {scores.get('As')} (반의도)
Conflict: {scores.get('Conflict')} [{scores.get('Hesitation')}]
Direction:{scores.get('Direction')} Speed:{scores.get('Speed')}

[Drive 분석]
{drive_str}

[정책]
Action: {policy['action']}
이유: {policy['reason']}

{policy['rule']}

[감지 신호]
갈등: {scores.get('Conflict_signals') or '없음'}
제약: {[c['constraint'] for c in scores.get('constraint_interventions',[])] or '없음'}
{review_str}

[원문]
{raw_text}
"""
    return prompt


SYSTEM_RULES = """
당신은 Decision Engine입니다.
반드시 Action에 따라 행동하세요.

[Action = SITUATION_BOARD 일때 - 최우선 규칙]
아래 형식만 출력하세요. 다른 말 절대 금지.

[A 속성명] 옵션1 / 옵션2 / 옵션3
[B 속성명] 옵션1 / 옵션2 / 옵션3
[C 속성명] 옵션1 / 옵션2 / 옵션3
[D 직접입력] 원하는 조건을 직접 입력하세요

가방 예시:
[A 용도] 여행용 / 출퇴근용 / 학생용
[B 사이즈] 소형(10L이하) / 중형(10~30L) / 대형(30L이상)
[C 예산] 3만원 이하 / 3~10만원 / 10만원 이상
[D 직접입력] 원하는 조건을 직접 입력하세요

노트북 예시:
[A 용도] 업무용 / 학생용 / 게임용
[B 화면크기] 13인치 / 15인치 / 17인치
[C 예산] 50만원 이하 / 50~100만원 / 100만원 이상
[D 직접입력] 원하는 조건을 직접 입력하세요

[절대 금지]
- SITUATION_BOARD인데 질문하는 것
- SITUATION_BOARD인데 설명하는 것
- 광고성 후기
- 수치 노출
"""


POLICE_RULES = """
당신은 Decision Engine 감시자입니다.
딱 한 단어만 출력: OK 또는 VIOLATION

체크:
1. S2이고 I_hat>0인데 역질문 → VIOLATION
2. 상황판에 물리 불가능 옵션 → VIOLATION
3. 광고성 후기 포함 → VIOLATION
4. 이상 없으면 → OK
"""
