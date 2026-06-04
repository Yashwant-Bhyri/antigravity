from __future__ import annotations

from dataclasses import dataclass, field


COVERAGE_WEIGHTS: dict[str, float] = {
    "voluntary":         1.0,
    "recovered_deep":    0.7,
    "recovered_surface": 0.4,
    "missed":            0.0,
    "incorrect":        -0.2,
    "not_evaluated":     0.0,
}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass
class CoverageDimension:
    id: str
    label: str
    description: str
    expected_approaches: list[str]
    surfacing_question: str
    weight: float
    depth_eligible: bool = False
    surface_kind: str = "breadth"
    coverage_state: str = "not_evaluated"
    candidate_response: str = ""
    surfacing_attempted: bool = False

    def weighted_score(self) -> float:
        return self.weight * COVERAGE_WEIGHTS.get(self.coverage_state, 0.0)


@dataclass
class AnswerCoverageMap:
    application_question: str
    implementation_anchor: str
    dimensions: list[CoverageDimension] = field(default_factory=list)
    total_weight: float = 0.0
    coverage_score: float = 0.0
    coverage_confidence: float = 0.0
    grounding_question: str = ""
    grounding_needed: bool = False
    max_depth_level: int = 3
    depth_allowed_terms: list[str] = field(default_factory=list)

    def compute_coverage_score(self) -> float:
        if self.total_weight == 0:
            return 0.0
        weighted_sum = sum(d.weighted_score() for d in self.dimensions)
        self.coverage_score = max(0.0, weighted_sum / self.total_weight)
        return self.coverage_score

    def unsurfaced_dimensions(self) -> list[CoverageDimension]:
        return [
            d for d in self.dimensions
            if d.coverage_state == "not_evaluated" and not d.surfacing_attempted
        ]

    def to_dict(self) -> dict:
        return {
            "application_question": self.application_question,
            "implementation_anchor": self.implementation_anchor,
            "coverage_score": self.coverage_score,
            "coverage_confidence": self.coverage_confidence,
            "total_weight": self.total_weight,
            "grounding_question": self.grounding_question,
            "grounding_needed": self.grounding_needed,
            "max_depth_level": self.max_depth_level,
            "depth_allowed_terms": list(self.depth_allowed_terms),
            "dimensions": [
                {
                    "id": d.id,
                    "label": d.label,
                    "description": d.description,
                    "expected_approaches": d.expected_approaches,
                    "surfacing_question": d.surfacing_question,
                    "weight": d.weight,
                    "depth_eligible": d.depth_eligible,
                    "surface_kind": d.surface_kind,
                    "coverage_state": d.coverage_state,
                    "candidate_response": d.candidate_response,
                    "surfacing_attempted": d.surfacing_attempted,
                }
                for d in self.dimensions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerCoverageMap":
        if not isinstance(data, dict):
            data = {}
        dims = [
            CoverageDimension(
                id=str(d.get("id", d.get("dimension_id", ""))),
                label=str(d.get("label", "")),
                description=str(d.get("description", "")),
                expected_approaches=_safe_str_list(d.get("expected_approaches", [])),
                surfacing_question=str(d.get("surfacing_question", "")),
                weight=max(0.0, _safe_float(d.get("weight", d.get("signal_weight", 1.5)), 1.5)),
                depth_eligible=bool(d.get("depth_eligible", False)),
                surface_kind=str(d.get("surface_kind", "breadth") or "breadth"),
                coverage_state=str(d.get("coverage_state", "not_evaluated")),
                candidate_response=str(d.get("candidate_response", "")),
                surfacing_attempted=bool(d.get("surfacing_attempted", False)),
            )
            for d in (data.get("dimensions") or [])
            if isinstance(d, dict)
        ]
        total_weight = _safe_float(data.get("total_weight", sum(d.weight for d in dims)), sum(d.weight for d in dims))
        return cls(
            application_question=str(data.get("application_question", "")),
            implementation_anchor=str(data.get("implementation_anchor", "")),
            dimensions=dims,
            total_weight=total_weight,
            coverage_score=_safe_float(data.get("coverage_score", 0.0), 0.0),
            coverage_confidence=max(0.0, min(1.0, _safe_float(data.get("coverage_confidence", 0.0), 0.0))),
            grounding_question=str(data.get("grounding_question", "") or ""),
            grounding_needed=bool(data.get("grounding_needed", False)),
            max_depth_level=max(1, min(4, int(_safe_float(data.get("max_depth_level", 3), 3)))),
            depth_allowed_terms=_safe_str_list(data.get("depth_allowed_terms", [])),
        )
