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


@dataclass
class CoverageDimension:
    id: str
    label: str
    description: str
    expected_approaches: list[str]
    surfacing_question: str
    weight: float
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
            "dimensions": [
                {
                    "id": d.id,
                    "label": d.label,
                    "description": d.description,
                    "expected_approaches": d.expected_approaches,
                    "surfacing_question": d.surfacing_question,
                    "weight": d.weight,
                    "coverage_state": d.coverage_state,
                    "candidate_response": d.candidate_response,
                    "surfacing_attempted": d.surfacing_attempted,
                }
                for d in self.dimensions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerCoverageMap":
        dims = [
            CoverageDimension(
                id=str(d.get("id", d.get("dimension_id", ""))),
                label=str(d.get("label", "")),
                description=str(d.get("description", "")),
                expected_approaches=list(d.get("expected_approaches", [])),
                surfacing_question=str(d.get("surfacing_question", "")),
                weight=float(d.get("weight", d.get("signal_weight", 1.5))),
                coverage_state=str(d.get("coverage_state", "not_evaluated")),
                candidate_response=str(d.get("candidate_response", "")),
                surfacing_attempted=bool(d.get("surfacing_attempted", False)),
            )
            for d in (data.get("dimensions") or [])
            if isinstance(d, dict)
        ]
        total_weight = float(data.get("total_weight", sum(d.weight for d in dims)))
        return cls(
            application_question=str(data.get("application_question", "")),
            implementation_anchor=str(data.get("implementation_anchor", "")),
            dimensions=dims,
            total_weight=total_weight,
            coverage_score=float(data.get("coverage_score", 0.0)),
            coverage_confidence=float(data.get("coverage_confidence", 0.0)),
        )
