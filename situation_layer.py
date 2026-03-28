from __future__ import annotations

"""
Decision Structure Engine - Full deterministic prototype
Built from the user's thesis-style document.

Principles:
- LLM is NOT used for decision logic.
- Natural language is converted into state -> mode -> board.
- Boards are always rendered in full.
- Color is a separate layer shown above the board when needed.
- Context / Specification input are pre-board layers.
- Constraint sensor only detects; Constraint layer performs action.

Run:
  python3 decision_structure_engine_full.py --demo
  python3 decision_structure_engine_full.py --query "유통기간 긴 우유 찾아줘"
  python3 decision_structure_engine_full.py --chat
  python3 decision_structure_engine_full.py --query "노트북 추천해줘" --json
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
import argparse
import json
import re
import sys


# ============================================================
# Data Models
# ============================================================

@dataclass
class SensorState:
    # Core state vector S = (I, C, R, A, H)
    intent: float = 0.0
    conflict: float = 0.0
    resistance: float = 0.0
    anti_intent: float = 0.0
    hesitation: float = 0.0

    # Conflict 6-axis C = (S, F, T, D, P, K)
    safety: float = 0.0
    function: float = 0.0
    timing: float = 0.0
    delivery: float = 0.0
    price: float = 0.0
    comparison: float = 0.0

    # Additional signals
    risk: int = 0
    product: Optional[str] = None
    product_group: Optional[str] = None
    mapped_product: Optional[str] = None
    context: Optional[str] = None
    spec_value: Optional[str] = None

    desire: bool = False
    needs_context: bool = False
    needs_spec: bool = False
    direct_mapping: bool = False
    vs_detected: bool = False
    vs_choice: Optional[str] = None  # 사용자가 VS에서 선택한 옵션
    bundle: bool = False
    solution: bool = False
    multi_candidate: bool = False

    conditions: Dict[str, str] = field(default_factory=dict)
    options: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class BoardRender:
    mode: str
    explanation: Optional[str] = None
    pre_input: Optional[str] = None
    color_layer: Optional[str] = None
    board: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_text(self, query: str) -> str:
        blocks = [f"QUERY: {query}", f"MODE: {self.mode}"]
        if self.explanation:
            blocks.append("\n[설명]\n" + self.explanation)
        if self.pre_input:
            blocks.append("\n[선행 입력]\n" + self.pre_input)
        if self.color_layer:
            blocks.append("\n[컬러 레이어]\n" + self.color_layer)
        if self.board:
            blocks.append("\n[상황판]\n" + self.board)
        if self.notes:
            blocks.append("\n[비고]\n" + "\n".join(f"- {n}" for n in self.notes))
        return "\n".join(blocks)


@dataclass
class SessionState:
    last_query: Optional[str] = None
    pending_mode: Optional[str] = None
    pending_product: Optional[str] = None
    pending_context: Optional[str] = None
    pending_spec_required: bool = False
    pending_options: List[str] = field(default_factory=list)


# ============================================================
# Engine
# ============================================================

class DecisionStructureEngine:
    """Deterministic engine implementing the thesis architecture."""

    def __init__(self) -> None:
        # Canonical products / categories used in the thesis and tests
        self.products = [
            "노트북", "데스크탑", "컴퓨터", "가방", "타이어", "냉장고", "에어컨",
            "우유", "사과", "연어", "소파", "쇼파", "정수기", "책", "유아책", "아동서적",
            "샴푸", "다이어트 보조제", "보조제", "영양제", "청소기", "크리너", "실리콘", "소고기"
        ]

        # Color-dominant categories (color shown above the board, never inside the board)
        self.color_dominant = {"가방", "소파", "쇼파", "의류", "옷"}

        # Context-first categories
        self.context_required = {"냉장고", "에어컨", "소파", "쇼파", "세탁기", "TV", "식탁"}

        # Specification-first categories
        self.spec_required = {"타이어", "공구", "필터", "잉크", "부품", "배터리"}

        # Health-sensitive categories
        self.health_sensitive_keywords = [
            "다이어트 제품", "다이어트 보조제", "보조제", "영양제", "건강보조식품", "살 빠지는", "약"
        ]

        # Bundle and solution
        self.bundle_keywords = ["전집", "세트", "단권", "아동서적", "유아책"]
        self.solution_keywords = ["러닝", "달리기", "캠핑", "등산"]

        # Direct Mapping rules: (required_keywords, mapped_product, explanation)
        self.direct_mapping_rules: List[Tuple[Tuple[str, ...], str, str]] = [
            (
                ("우유", "유통기간", "긴"),
                "멸균우유",
                "유통기간 긴 우유 찾으시는 거면\n멸균우유 선택하시면 됩니다 👍\n\n✔ 상온 보관 가능\n✔ 유통기간 길어서 쟁여두기 좋음",
            ),
            (
                ("사과", "당도"),
                "고당도 사과",
                "당도 높은 사과 찾으시는 거면\n부사/홍로/감홍 계열을 먼저 보시면 됩니다 👍\n\n✔ 당도 높음\n✔ 아삭한 식감",
            ),
            (
                ("타이어", "소음"),
                "저소음 타이어",
                "소음 적은 타이어 찾으시는 거면\n컴포트 타입 타이어가 적합합니다 👍\n\n✔ 저소음 중심\n✔ 승차감 위주",
            ),
            (
                ("소고기", "A++", "부드러"),
                "프리미엄 스테이크용 소고기",
                "A++ 등급 소고기는 마블링이 많아\n육질이 부드럽고 풍미가 좋은 스테이크용입니다 👍",
            ),
        ]

        # VS templates
        self.vs_templates: Dict[Tuple[str, str], str] = {
            ("노트북", "데스크탑"): "어떤 쪽이 더 맞으세요?\n\n노트북 → 이동 가능, 공간 절약\n데스크탑 → 성능 좋음, 업그레이드 가능",
            ("가죽", "패브릭"): "어떤 쪽이 더 맞으세요?\n\n가죽 → 털 관리 쉽고 닦기 편함 / 대신 스크래치 약함\n패브릭 → 스크래치 강함 / 대신 털 붙고 관리 어려움",
            ("노르웨이산", "덴마크산"): "어떤 쪽이 더 맞으세요?\n\n노르웨이산 → 지방 많고 부드러움 / 회·스테이크에 적합\n덴마크산 → 담백하고 깔끔 / 샐러드·구이에 적합",
            ("구매", "렌탈"): "어떤 방식이 더 맞으세요?\n\n구매 → 제품 소유, 유지관리 직접\n렌탈 → 월 요금, 관리 서비스 포함",
        }

        # Product attribute space for TopK(R(C) \ F(Q))
        self.attribute_space: Dict[str, List[str]] = {
            "멸균우유": ["브랜드", "용량", "구성", "보관", "용도", "가격", "배송"],
            "고당도 사과": ["품종", "크기", "포장", "가격"],
            "저소음 타이어": ["차종", "주행 스타일", "소음 수준", "승차감", "브랜드", "가격", "장착"],
            "노트북": ["성능", "가격", "브랜드", "발열/소음", "배송", "비교 기준"],
            "가방": ["종류", "용도", "크기", "가격", "브랜드", "비교 기준"],
            "소파": ["형태", "구조", "쿠션감", "소재", "관리", "반려동물", "가격", "배송/설치"],
            "연어": ["용도", "형태", "중량", "신선도", "손질 상태", "원산지 옵션", "가격", "배송"],
            "유아책": ["구성", "책 유형", "발달", "권 수", "가격"],
            "러닝": ["목적", "수준", "구성", "환경", "예산"],
            "냉장고@가정": ["용량/가족", "기능", "구매 시점", "배송/설치", "가격", "비교 기준"],
            "냉장고@사무실": ["용량", "형태", "용도", "내구성", "소음", "가격", "설치"],
            "냉장고@업소": ["용량", "형태", "용도", "내구성", "효율", "가격", "설치"],
            "에어컨@가정": ["형태", "공간 크기", "기능", "소음", "가격", "설치"],
            "에어컨@업소": ["형태", "공간 크기", "기능", "효율", "가격", "설치"],
        }

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------
    def analyze(self, query: str) -> SensorState:
        q = query.strip()
        s = SensorState()
        s.product = self._detect_product(q)
        s.product_group = s.product
        s.conditions = self._extract_conditions(q)
        s.context = s.conditions.get("context")
        s.intent = self._intent_score(q)

        # Desire / style ambiguity
        if any(k in q for k in ["이쁜", "예쁜", "감성", "스타일", "느낌"]):
            s.desire = True
            s.notes.append("감성형 질문 감지")

        # Health-sensitive
        if any(k in q for k in self.health_sensitive_keywords):
            s.risk = 1
            s.notes.append("건강/제약 카테고리 감지")

        # Spec-needed products
        if s.product in self.spec_required:
            s.needs_spec = True
            spec = self._extract_spec(q)
            if spec:
                s.spec_value = spec
                s.conditions["spec"] = spec
            s.notes.append("규격 기반 제품 감지")

        # Context-needed products
        if s.product in self.context_required:
            s.needs_context = True
            s.notes.append("Context 선행 선택 필요")

        # Bundle / Solution
        if ("책" in q and any(k in q for k in ["아이", "유아", "아동", "두 살", "두살", "세트", "전집"])) or any(k in q for k in self.bundle_keywords):
            s.bundle = True
            s.product_group = "유아책"
        if any(k in q for k in self.solution_keywords) and not any(k in q for k in ["러닝화", "운동화", "신발", "워치", "이어폰"]):
            s.solution = True
            s.product_group = "러닝"

        # VS detection
        options = self._extract_vs_options(q)
        if len(options) >= 2:
            s.vs_detected = True
            s.options = options
            s.conflict = max(s.conflict, 0.8)
            s.hesitation = max(s.hesitation, 0.6)
            s.notes.append("VS 구조 감지")

        # Direct Mapping
        mapped = self._direct_mapping(q)
        if mapped:
            s.direct_mapping = True
            s.mapped_product, _ = mapped
            s.product_group = s.mapped_product
            s.conflict = min(max(s.conflict, 0.05), 0.15)
            s.notes.append(f"직접 매핑: {s.mapped_product}")

        # Multi-candidate: product not fixed but direction exists
        if self._need_multi_candidate(q, s):
            s.multi_candidate = True
            s.notes.append("다중 후보 방향 선택 필요")

        # Conflict 6-axis
        self._fill_axes(q, s)
        s.conflict = max(s.conflict, self._conflict_from_axes(s))

        # High-conflict canonical categories
        if s.product in {"노트북", "냉장고"} and not s.direct_mapping and not s.vs_detected and not s.needs_spec:
            s.conflict = max(s.conflict, 0.75)
            s.hesitation = max(s.hesitation, 0.4)

        # Resistance / Anti-intent / Hesitation
        if any(k in q for k in ["비싸", "부담", "걱정"]):
            s.resistance = max(s.resistance, 0.7)
        if any(k in q for k in ["싫어", "말고", "빼고", "제외"]):
            s.anti_intent = max(s.anti_intent, 0.6)
        if any(k in q for k in ["고민", "모르겠", "맞는지", "괜찮을까"]):
            s.hesitation = max(s.hesitation, 0.7)

        return s

    def decide_mode(self, s: SensorState) -> str:
        """M = f(S) approximated deterministically."""
        # Ordering matters
        if s.desire:
            return "desire_layer"
        if s.needs_spec and not s.spec_value:
            return "spec_input"
        if s.risk == 1:
            return "constraint"
        if s.vs_detected and getattr(s, 'vs_choice', None):
            return "vs_selected"
        if s.vs_detected:
            return "vs_mode"
        if s.solution:
            return "solution_mode"
        if s.bundle:
            return "bundle_mode"
        if s.multi_candidate:
            return "multi_candidate_mode"
        if s.needs_context and not s.context:
            return "context_preselect"
        if s.needs_context and s.context:
            return "context_panel"
        if s.direct_mapping:
            return "direct_mapping"
        if s.conflict >= 0.6:
            return "conflict_mode"
        if s.product and s.intent >= 0.7:
            return "panel_mode"
        return "recommend"

    def respond(self, query: str, session: Dict[str, Any] = None) -> Dict[str, Any]:
        s = self.analyze(query)
        # VS 선택 세션 주입
        if session and session.get("vs_choice"):
            s.vs_choice = session["vs_choice"]
            s.vs_detected = True
            s.options = session.get("vs_options", s.options)
        mode = self.decide_mode(s)
        render = self._render_mode(query, s, mode)
        return {
            "query": query,
            "sensor_state": asdict(s),
            "mode": mode,
            "render": asdict(render),
        }

    # --------------------------------------------------------
    # Mode rendering
    # --------------------------------------------------------
    def _render_mode(self, query: str, s: SensorState, mode: str) -> BoardRender:
        if mode == "desire_layer":
            return BoardRender(
                mode=mode,
                explanation="감성/취향형 질문으로 감지되었습니다. 이 경우 텍스트 대신 욕망 스토리보드(이미지 선택 레이어)로 연결합니다.",
                notes=[
                    "이미지 10개 제시 → 사용자 선택 → 취향 벡터 생성 → 추천",
                    "기존 구조를 수정하지 않고 별도 레이어로 확장",
                ],
            )

        if mode == "spec_input":
            return BoardRender(
                mode=mode,
                pre_input=self._build_spec_input(s.product or "규격 제품"),
                notes=[
                    "규격 제품은 선택이 아니라 입력부터 시작합니다",
                    "규격 입력 이후에만 상황판을 생성합니다",
                ],
            )

        if mode == "constraint":
            return BoardRender(
                mode=mode,
                explanation="건강/제약 카테고리로 감지되어 Constraint Layer를 먼저 실행합니다.",
                board=self._board_constraint(),
                notes=[
                    "제약 센서는 감지만 수행합니다",
                    "Constraint Layer가 실제 질문/개입을 수행합니다",
                ],
            )

        if mode == "vs_mode":
            options = s.options[:2]
            explanation = self._build_vs_explanation(options)
            # 1단계: 설명만 출력, 상황판은 사용자 선택 후 2단계에서 출력
            return BoardRender(
                mode=mode,
                explanation=explanation,
                board=None,
                notes=[
                    f"VS_OPTIONS:{','.join(options)}",
                    "사용자 선택 후 vs_selected 모드로 상황판 진입"
                ]
            )

        if mode == "vs_selected":
            options = s.options[:2]
            color_layer = None
            if tuple(options) == ("가죽", "패브릭"):
                color_layer = self._color_layer(["베이지", "그레이", "블랙", "브라운"])
            board = self._board_after_vs(tuple(options))
            return BoardRender(mode=mode, color_layer=color_layer, board=board)

        if mode == "solution_mode":
            return BoardRender(
                mode=mode,
                explanation="이 질문은 단일 제품보다 활동 전체 구성이 중요한 질문으로 판단되었습니다.",
                board=self._board_solution(),
            )

        if mode == "bundle_mode":
            return BoardRender(
                mode=mode,
                explanation="이 질문은 단품보다 구성/세트 단위 추천이 더 적합합니다.",
                board=self._board_bundle(),
            )

        if mode == "multi_candidate_mode":
            return BoardRender(
                mode=mode,
                explanation="이 질문은 제품 하나가 아니라 방향 선택이 먼저 필요한 구조입니다.",
                board=self._board_multi_candidate(query),
            )

        if mode == "context_preselect":
            return BoardRender(
                mode=mode,
                pre_input="어디에서 사용하시나요?\n\n가정 / 사무실 / 업소",
                notes=[
                    "Context는 상황판 안에 넣지 않습니다",
                    "Context 선택 후 상황판 전체를 재생성합니다",
                ],
            )

        if mode == "context_panel":
            return BoardRender(
                mode=mode,
                explanation=f"{s.context} 기준으로 상황판을 재생성했습니다.",
                board=self._board_context_panel(s.product or "", s.context or "가정"),
            )

        if mode == "direct_mapping":
            mapped_product, explanation = self._direct_mapping(query) or (s.mapped_product or "", "")
            color_layer = None
            if mapped_product in self.color_dominant:
                color_layer = self._color_layer(["블랙", "베이지", "브라운", "그레이"])
            return BoardRender(
                mode=mode,
                explanation=explanation,
                color_layer=color_layer,
                board=self._board_direct_mapping(mapped_product),
                notes=["Quick Panel 최소 차원 공식 적용: 최소 4개, 권장 5~7개, 최대 7개"],
            )

        if mode == "conflict_mode":
            color_layer = None
            if (s.product_group or s.product or "") in self.color_dominant:
                color_layer = self._color_layer(["블랙", "베이지", "브라운", "그레이"])
            return BoardRender(
                mode=mode,
                color_layer=color_layer,
                board=self._board_conflict(s.product_group or s.product or "일반제품"),
            )

        if mode == "panel_mode":
            color_layer = None
            if (s.product_group or s.product or "") in self.color_dominant:
                color_layer = self._color_layer(["블랙", "베이지", "브라운", "그레이"])
            return BoardRender(
                mode=mode,
                color_layer=color_layer,
                board=self._board_panel(s.product_group or s.product or "일반제품"),
            )

        return BoardRender(mode=mode, explanation="기본 추천 모드입니다. 별도 구조를 감지하지 못했습니다.")

    # --------------------------------------------------------
    # Detection helpers
    # --------------------------------------------------------
    def _intent_score(self, q: str) -> float:
        trigger = ["추천", "찾아줘", "찾고", "사려고", "사줄", "알아봐", "뭐가 좋아", "어떤 것"]
        return 0.9 if any(t in q for t in trigger) else 0.6

    def _detect_product(self, q: str) -> Optional[str]:
        for p in self.products:
            if p in q:
                return p
        if "러닝" in q:
            return "러닝"
        return None

    def _extract_conditions(self, q: str) -> Dict[str, str]:
        cond: Dict[str, str] = {}
        if "유통기간" in q and "긴" in q:
            cond["shelf_life"] = "long"
        if "당도" in q and ("높" in q or "달" in q):
            cond["sweetness"] = "high"
        if "소음" in q and ("적" in q or "없" in q):
            cond["noise"] = "low"
        if "A++" in q:
            cond["grade"] = "A++"
        if "부드러" in q:
            cond["texture"] = "soft"
        if "블랙" in q:
            cond["color"] = "블랙"
        if "베이지" in q:
            cond["color"] = "베이지"
        if "브라운" in q:
            cond["color"] = "브라운"
        if "그레이" in q:
            cond["color"] = "그레이"
        if "우리집" in q or "가정" in q or "집" in q:
            cond["context"] = "가정"
        if "사무실" in q or "탕비실" in q:
            cond["context"] = "사무실"
        if "업소" in q or "식당" in q or "매장" in q:
            cond["context"] = "업소"
        return cond

    def _extract_spec(self, q: str) -> Optional[str]:
        # tire-like patterns: 225/55R17 or 225 55 R17
        m = re.search(r"(\d{3})\s*/?\s*(\d{2})\s*[Rr]\s*(\d{2})", q)
        if m:
            return f"{m.group(1)}/{m.group(2)}R{m.group(3)}"
        return None

    def _extract_vs_options(self, q: str) -> List[str]:
        pairs = [
            ("노트북", "데스크탑"),
            ("가죽", "패브릭"),
            ("노르웨이산", "덴마크산"),
            ("구매", "렌탈"),
            ("캐리어", "백팩"),
        ]
        found: List[str] = []
        for a, b in pairs:
            if a in q and b in q:
                found = [a, b]
                break
        if found:
            return found
        if "vs" in q.lower():
            chunks = [c.strip() for c in re.split(r"\bvs\b", q, flags=re.I) if c.strip()]
            return chunks[:2]
        return []

    def _need_multi_candidate(self, q: str, s: SensorState) -> bool:
        if s.vs_detected or s.direct_mapping or s.desire or s.bundle or s.solution:
            return False
        # activity / broad directional questions
        if "제품" in q and any(k in q for k in ["러닝", "운동", "캠핑"]):
            return True
        # ambiguous “what kind of product” questions
        if s.product == "컴퓨터" and any(k in q for k in ["노트북", "데스크탑"]):
            return True
        return False

    def _fill_axes(self, q: str, s: SensorState) -> None:
        if any(k in q for k in ["발열", "소음", "스크래치", "안전", "거북목"]):
            s.safety = 0.8
        if any(k in q for k in ["성능", "기능", "고성능", "양문형", "김치냉장고", "빠르"]):
            s.function = 0.8
        if any(k in q for k in ["지금", "급함", "바로", "당장", "비교 후"]):
            s.timing = 0.7
        if any(k in q for k in ["배송", "설치", "장착", "새벽 배송"]):
            s.delivery = 0.8
        if any(k in q for k in ["가격", "가성비", "비싸", "저가", "중가", "고가"]):
            s.price = 0.8
        if any(k in q for k in ["브랜드", "비교", "디자인", "가죽", "패브릭", "원산지"]):
            s.comparison = 0.8

    def _conflict_from_axes(self, s: SensorState) -> float:
        axes = [s.safety, s.function, s.timing, s.delivery, s.price, s.comparison]
        active = [a for a in axes if a > 0]
        if not active:
            return 0.0
        return min(1.0, sum(active) / max(1, len(active)) * (1.0 if len(active) >= 2 else 0.5))

    def _direct_mapping(self, q: str) -> Optional[Tuple[str, str]]:
        for keys, mapped, explanation in self.direct_mapping_rules:
            if all(k in q for k in keys):
                return mapped, explanation
        return None

    # --------------------------------------------------------
    # Board builders
    # --------------------------------------------------------
    def _render_board(self, items: List[Tuple[str, List[str]]]) -> str:
        chunks = ["----------------------------", ""]
        for label, options in items:
            chunks.append(f"[{label}]")
            chunks.append(" / ".join(options))
            chunks.append("")
        if items and items[-1][0] != "E 직접입력":
            chunks.append("[E 직접입력]")
            chunks.append("원하는 조건을 자유롭게 입력하세요")
            chunks.append("")
        chunks.append("----------------------------")
        return "\n".join(chunks)

    def _color_layer(self, colors: List[str]) -> str:
        return "[컬러]\n" + " / ".join(colors)

    def _build_spec_input(self, product: str) -> str:
        if product == "타이어":
            return "[타이어 규격 입력]\n예: 225/55R17\n\n직접 입력 / 모르겠어요"
        return f"[{product} 규격 입력]\n직접 입력 / 모르겠어요"

    def _build_vs_explanation(self, options: List[str]) -> str:
        if len(options) < 2:
            return "선택지 비교 정보가 부족합니다."
        key = (options[0], options[1])
        rev_key = (options[1], options[0])
        if key in self.vs_templates:
            return self.vs_templates[key]
        if rev_key in self.vs_templates:
            return self.vs_templates[rev_key]
        return "어떤 쪽이 더 맞으세요?\n\n" + "\n".join(f"{opt} → 핵심 차이 비교 필요" for opt in options[:2])

    def _board_after_vs(self, pair: Tuple[str, str]) -> str:
        if pair == ("노트북", "데스크탑"):
            return self._render_board([
                ("사용 목적", ["학습", "게임", "혼합"]),
                ("성능 수준", ["기본", "중급", "고성능"]),
                ("화면 크기", ["13인치", "15인치", "17인치"]),
                ("무게", ["가벼움", "보통", "상관없음"]),
                ("발열/소음", ["적음", "보통", "상관없음"]),
                ("배터리", ["긴 사용", "보통"]),
                ("브랜드", ["삼성", "LG", "ASUS", "상관없음"]),
                ("가격", ["저가", "중가", "고가"]),
                ("배송", ["빠른 배송", "일반 배송"]),
            ])
        if pair == ("가죽", "패브릭"):
            return self._render_board([
                ("형태", ["2인용", "3인용", "4인용 이상"]),
                ("구조", ["일자형", "코너형", "모듈형"]),
                ("쿠션감", ["푹신", "중간", "탄탄"]),
                ("소재", ["패브릭", "기능성 패브릭"]),
                ("관리", ["세탁 가능", "커버 분리", "상관없음"]),
                ("반려동물", ["털 적음", "스크래치 강함", "상관없음"]),
                ("가격", ["저가", "중가", "고가"]),
                ("배송/설치", ["설치 포함", "빠른 배송", "직접 설치"]),
            ])
        if pair == ("노르웨이산", "덴마크산"):
            return self._render_board([
                ("용도", ["회", "구이", "스테이크"]),
                ("형태", ["슬라이스", "필렛", "덩어리"]),
                ("중량", ["200g", "500g", "1kg", "2kg"]),
                ("신선도", ["냉장", "냉동"]),
                ("손질 상태", ["손질 완료", "직접 손질"]),
                ("원산지 옵션", ["노르웨이", "상관없음"]),
                ("가격", ["중가", "고가", "프리미엄"]),
                ("배송", ["새벽 배송", "일반 배송"]),
            ])
        if pair == ("구매", "렌탈"):
            return self._render_board([
                ("사용 장소", ["가정", "사무실"]),
                ("방식", ["냉온정", "정수만"]),
                ("관리", ["방문 관리", "셀프 관리"]),
                ("월 요금", ["저가", "중가", "고가"]),
            ])
        return self._render_board([("선택", list(pair))])

    def _board_constraint(self) -> str:
        return self._render_board([
            ("목표", ["체중 감량", "체지방 감소"]),
            ("상태", ["초기", "진행"]),
            ("알러지", ["있음", "없음"]),
            ("복용약", ["있음", "없음"]),
            ("카페인", ["있음", "없음"]),
            ("가격", ["저가", "중가", "고가"]),
            ("형태", ["정제", "분말", "음료"]),
        ])

    def _board_solution(self) -> str:
        return self._render_board([
            ("목적", ["다이어트", "체력", "기록"]),
            ("수준", ["입문", "중급", "고급"]),
            ("구성", ["신발", "의류", "워치", "이어폰"]),
            ("환경", ["실외", "실내"]),
            ("예산", ["저가", "중가", "고가"]),
        ])

    def _board_bundle(self) -> str:
        return self._render_board([
            ("구성", ["단권", "세트", "전집"]),
            ("책 유형", ["그림책", "사운드북", "촉감책"]),
            ("발달", ["언어", "감각", "정서"]),
            ("권 수", ["5권", "10권", "20권"]),
            ("가격", ["저가", "중가", "고가"]),
        ])

    def _board_multi_candidate(self, query: str) -> str:
        if "러닝" in query:
            return self._render_board([
                ("어떤 제품을 찾으세요?", ["러닝화", "러닝복", "스마트워치", "이어폰"]),
            ])
        return self._render_board([
            ("어떤 방향이 더 맞으세요?", ["제품군 A", "제품군 B", "제품군 C"]),
        ])

    def _board_context_panel(self, product: str, context: str) -> str:
        if product == "냉장고":
            if context == "사무실":
                return self._render_board([
                    ("용량", ["소형", "중형", "대형"]),
                    ("형태", ["1도어", "2도어", "쇼케이스형"]),
                    ("용도", ["음료 보관", "간식", "혼합"]),
                    ("내구성", ["기본", "고내구"]),
                    ("소음", ["적음", "상관없음"]),
                    ("가격", ["저가", "중가", "고가"]),
                    ("설치", ["직접 설치", "설치 포함"]),
                ])
            if context == "업소":
                return self._render_board([
                    ("용량", ["중형", "대형", "초대형"]),
                    ("형태", ["냉장형", "냉동형", "냉장냉동 분리형"]),
                    ("용도", ["식재료", "음료", "혼합"]),
                    ("내구성", ["기본", "고내구"]),
                    ("효율", ["기본", "고효율"]),
                    ("가격", ["중가", "고가", "프리미엄"]),
                    ("설치", ["설치 포함", "일정 협의"]),
                ])
            return self._render_board([
                ("용량/가족", ["1~2인", "3~4인", "대가족"]),
                ("기능", ["기본", "양문형", "김치냉장고 포함"]),
                ("구매 시점", ["지금 급함", "비교 후 구매"]),
                ("배송/설치", ["빠른 배송", "설치 포함", "직접 설치"]),
                ("가격", ["저가", "중가", "고가"]),
                ("비교 기준", ["브랜드", "가성비", "디자인"]),
            ])

        if product == "에어컨":
            if context == "업소":
                return self._render_board([
                    ("형태", ["스탠드", "시스템", "업소형"]),
                    ("공간 크기", ["중형", "대형", "초대형"]),
                    ("기능", ["냉방", "냉난방", "대용량"]),
                    ("효율", ["기본", "고효율"]),
                    ("가격", ["중가", "고가", "프리미엄"]),
                    ("설치", ["설치 포함", "일정 협의"]),
                ])
            return self._render_board([
                ("형태", ["벽걸이", "스탠드", "투인원"]),
                ("공간 크기", ["소형", "중형", "대형"]),
                ("기능", ["냉방만", "냉난방", "공기청정 포함"]),
                ("소음", ["적음", "보통", "상관없음"]),
                ("가격", ["저가", "중가", "고가"]),
                ("설치", ["설치 포함", "빠른 설치", "날짜 협의"]),
            ])

        return self._board_panel(product)

    def _board_direct_mapping(self, mapped_product: str) -> str:
        if mapped_product == "멸균우유":
            attrs = self._topk_attributes(mapped_product, fixed_conditions={"shelf_life": "long"}, k=7)
            item_map = {
                "브랜드": ["서울우유", "매일", "남양", "수입", "상관없음"],
                "용량": ["200ml", "500ml", "1L", "대용량"],
                "구성": ["단품", "6팩", "12팩", "박스"],
                "보관": ["상온", "냉장"],
                "용도": ["가정용", "캠핑", "사무실"],
                "가격": ["저가", "중가", "고가"],
                "배송": ["빠른 배송", "일반 배송"],
            }
            return self._render_board([(a, item_map[a]) for a in attrs])

        if mapped_product == "고당도 사과":
            attrs = self._topk_attributes(mapped_product, fixed_conditions={"sweetness": "high"}, k=4)
            item_map = {
                "품종": ["부사", "홍로", "감홍", "상관없음"],
                "크기": ["소과", "중과", "대과"],
                "포장": ["가정용", "선물용"],
                "가격": ["저가", "중가", "고가"],
            }
            return self._render_board([(a, item_map[a]) for a in attrs])

        if mapped_product == "저소음 타이어":
            attrs = self._topk_attributes(mapped_product, fixed_conditions={"noise": "low"}, k=7)
            item_map = {
                "차종": ["세단", "SUV", "경차"],
                "주행 스타일": ["도심", "장거리", "혼합"],
                "소음 수준": ["최저", "보통"],
                "승차감": ["부드러움", "보통"],
                "브랜드": ["한국", "미쉐린", "콘티넨탈", "상관없음"],
                "가격": ["중가", "고가"],
                "장착": ["포함", "미포함"],
            }
            return self._render_board([(a, item_map[a]) for a in attrs])

        if mapped_product == "프리미엄 스테이크용 소고기":
            return self._render_board([
                ("부위", ["등심", "안심", "채끝"]),
                ("원산지", ["한우", "수입 (미국산 등)"]),
                ("가격", ["고가", "프리미엄"]),
                ("형태", ["스테이크용", "구이용"]),
            ])

        return self._render_board([("제품", [mapped_product])])

    def _board_conflict(self, product: str) -> str:
        if product == "노트북":
            return self._render_board([
                ("성능", ["고성능", "일반"]),
                ("가격", ["저가", "중가", "고가"]),
                ("브랜드", ["삼성", "LG", "ASUS", "상관없음"]),
                ("발열/소음", ["적음", "보통", "상관없음"]),
                ("배송", ["빠른 배송", "일반 배송"]),
                ("비교 기준", ["가성비", "성능", "디자인"]),
            ])
        if product == "냉장고":
            return self._render_board([
                ("용량/가족", ["1~2인", "3~4인", "대가족"]),
                ("기능", ["기본", "양문형", "김치냉장고 포함"]),
                ("구매 시점", ["지금 급함", "비교 후 구매"]),
                ("배송/설치", ["빠른 배송", "설치 포함", "직접 설치"]),
                ("가격", ["저가", "중가", "고가"]),
                ("비교 기준", ["브랜드", "가성비", "디자인"]),
            ])
        return self._board_panel(product)

    def _board_panel(self, product: str) -> str:
        if product == "가방":
            return self._render_board([
                ("종류", ["백팩", "크로스백", "토트백", "캐리어"]),
                ("용도", ["출퇴근", "여행", "운동", "데일리"]),
                ("크기", ["소형", "중형", "대형"]),
                ("가격", ["저가", "중가", "고가"]),
                ("브랜드", ["국내", "해외", "상관없음"]),
                ("비교 기준", ["가성비", "디자인", "내구성"]),
            ])
        if product == "책" or product == "유아책":
            return self._board_bundle()
        return self._render_board([
            ("기준", ["기본", "중급", "고급"]),
            ("가격", ["저가", "중가", "고가"]),
            ("브랜드", ["상관없음", "국내", "해외"]),
            ("비교 기준", ["가성비", "디자인", "성능"]),
        ])

    # --------------------------------------------------------
    # Quick Panel minimum-dimension rule
    # --------------------------------------------------------
    def _topk_attributes(self, category: str, fixed_conditions: Dict[str, str], k: int = 7) -> List[str]:
        """
        Quick Panel minimum-dimension rule from the thesis.

        X = TopK(R(C) minus F(Q))
        - minimum 4 attributes
        - recommended 5~7
        - maximum 7
        """
        attrs = list(self.attribute_space.get(category, []))
        # In this prototype, fixed_conditions are semantic and not literal attribute names,
        # so we only remove direct attribute matches if any exist.
        fixed_keys = set(fixed_conditions.keys())
        filtered = [a for a in attrs if a not in fixed_keys]

        k = max(4, min(7, k))
        return filtered[:k]


# ============================================================
# Session-oriented helper (optional sequential test)
# ============================================================

class EngineSession:
    def __init__(self, engine: DecisionStructureEngine) -> None:
        self.engine = engine
        self.state = SessionState()

    def ask(self, text: str) -> Dict[str, Any]:
        # Simple single-turn processing for now; keeps state for future extension.
        self.state.last_query = text
        return self.engine.respond(text)


# ============================================================
# CLI / Demos
# ============================================================

DEMO_QUERIES = [
    "유통기간 긴 우유 찾아줘",
    "노트북 추천해줘",
    "노트북으로 할까요 데스크탑으로 할까요?",
    "소파 구매하려는데요 가죽은 너무 스크래치 때문에 패브릭은 좋은데 강아지 털 때문에 고민 어떤것을 고를까요 추천 부탁해요",
    "노르웨이산 연어랑 덴마크산 연어랑 어떤것이 좋은지 추천좀 해줘요",
    "사무실에서 쓸 냉장고 추천해줘",
    "타이어 추천해줘",
    "다이어트 제품 어떤것 먹어야 살이 잘 빠질까?",
    "두 살 아이 책 추천해줘",
    "러닝 제품 추천해줘",
    "이쁜 가방 찾아줘",
]


def render_result(result: Dict[str, Any], as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, ensure_ascii=False, indent=2)
    rr = BoardRender(**result["render"])
    text = rr.to_text(result["query"])
    text += "\n\n[센서 상태]\n" + json.dumps(result["sensor_state"], ensure_ascii=False, indent=2)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Decision Structure Engine Full")
    parser.add_argument("--query", type=str, help="single query to process")
    parser.add_argument("--demo", action="store_true", help="run demo queries")
    parser.add_argument("--chat", action="store_true", help="interactive chat mode")
    parser.add_argument("--json", action="store_true", help="print json")
    args = parser.parse_args()

    engine = DecisionStructureEngine()

    if args.query:
        result = engine.respond(args.query)
        print(render_result(result, as_json=args.json))
        return 0

    if args.demo:
        for i, q in enumerate(DEMO_QUERIES, 1):
            print("=" * 80)
            print(f"DEMO {i}")
            print(render_result(engine.respond(q), as_json=args.json))
            print()
        return 0

    if args.chat:
        print("Decision Structure Engine chat mode. 종료하려면 exit 입력")
        session = EngineSession(engine)
        while True:
            try:
                q = input("\n사용자> ").strip()
            except EOFError:
                break
            if not q or q.lower() in {"exit", "quit"}:
                break
            result = session.ask(q)
            print(render_result(result, as_json=args.json))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
