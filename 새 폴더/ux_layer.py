# ===============================
# ux_layer.py
# 사용자 화면 출력
# 동현님 설계 / 로드 구현
# ===============================
#
# 역할:
# LLM 결과를 사용자에게 보여주는 레이어
# 출처 표시 / 수치 표시 / 경고 표시
# ===============================

def format_response(output, scores, policy, review_result=None):
    """
    최종 사용자 화면 구성
    """
    lines = []

    # 제약 경고 있으면 상단에 표시
    interventions = scores.get('constraint_interventions', [])
    if interventions:
        top = interventions[0]
        if top['intensity'] >= 0.8:
            lines.append(f"⚠️  {top['constraint']} 위험 높음")
        elif top['intensity'] >= 0.4:
            lines.append(f"⚡  {top['constraint']} 확인 필요")
        else:
            lines.append(f"💡  {top['constraint']} 참고")
        lines.append("")

    # LLM 응답
    lines.append(output)

    # 리뷰 출처 표시 (동현님 아이디어)
    if review_result and isinstance(review_result, dict):
        top3 = review_result.get('top3', [])
        if top3:
            lines.append("\n─────────────────────────────")
            lines.append("📊 리뷰 역추적 근거")
            for i, item in enumerate(top3, 1):
                p = item.get('product', {})
                sources = item.get('source_breakdown', {})
                lines.append(f"\n{i}. {p.get('title','')[:30]}")
                lines.append(f"   종합점수: {item.get('total_score', 0)}")
                if sources:
                    lines.append("   출처별 평가:")
                    for src, sc in sorted(sources.items(),
                                         key=lambda x: x[1], reverse=True):
                        bar = "+" * abs(int(sc)) if sc > 0 else "-" * abs(int(sc))
                        lines.append(f"   {src:<25} {bar or '0'}")

    return '\n'.join(lines)


def format_debug(scores, policy):
    """
    개발용 디버그 출력
    """
    return (
        f"\n{'='*50}\n"
        f"[수치] S={scores.get('S_type')} | "
        f"I_hat={scores.get('I_hat')} | "
        f"As={scores.get('As')} | "
        f"Conflict={scores.get('Conflict')} | "
        f"Dir={scores.get('Direction')} Spd={scores.get('Speed')}\n"
        f"[정책] {policy.get('action')} → {policy.get('reason')}\n"
        f"{'='*50}"
    )
