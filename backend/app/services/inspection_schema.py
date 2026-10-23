"""Schema for VLM-generated inspection results (lenient toward small-model quirks)."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

_WORD_CONFIDENCE = {"high": 0.9, "medium": 0.6, "moderate": 0.6, "low": 0.3, "critical": 0.95, "none": 0.0}
_SEVERITY_ALIASES = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "med": "medium",
    "low": "low",
    "minor": "low",
    "major": "high",
    "severe": "critical",
}


def coerce_confidence(v: Any) -> float:
    """Accept numeric confidence or verbal grades ("High" -> 0.9)."""
    if isinstance(v, str):
        cleaned = v.strip().lower().rstrip("%")
        if cleaned in _WORD_CONFIDENCE:
            return _WORD_CONFIDENCE[cleaned]
        try:
            return float(cleaned)
        except ValueError:
            return 0.5
    if isinstance(v, (int, float)):
        return float(v)
    return 0.5


class GeneratedDefect(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    defect_type: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("defect_type", "type", "name", "defect"),
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    location: str = ""
    bbox: list[float] | None = None
    evidence: str = Field(
        default="",
        validation_alias=AliasChoices("evidence", "concrete_visual_evidence", "visual_evidence", "description"),
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: Any) -> float:
        return coerce_confidence(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: Any) -> str:
        if isinstance(v, str):
            return _SEVERITY_ALIASES.get(v.strip().lower(), "medium")
        return "medium"


class GeneratedInspection(BaseModel):
    model_config = ConfigDict(extra="allow")

    verdict: str = Field(pattern="^(pass|fail|inconclusive)$")
    confidence: float = Field(ge=0.0, le=1.0)
    defects: list[GeneratedDefect] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    recommended_disposition: str = Field(pattern="^(accept|reject|rework|review)$")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: Any) -> float:
        return coerce_confidence(v)

    @field_validator("verdict", "recommended_disposition", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v
