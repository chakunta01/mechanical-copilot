"""Schema for LLM-generated process plans (the constrained output contract)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import Citation, InspectionPlanItem, coerce_str_list


class GeneratedOperation(BaseModel):
    model_config = ConfigDict(extra="allow")

    op_number: int = Field(ge=1, le=999)
    name: str = Field(min_length=1, max_length=200)
    machine: str = Field(min_length=1, max_length=200)
    tooling: list[str] = Field(default_factory=list)
    parameters: dict[str, float | int | str] = Field(default_factory=dict)
    description: str = ""
    inspection_checkpoints: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("tooling", "inspection_checkpoints", mode="before")
    @classmethod
    def _coerce_str_lists(cls, v: Any) -> list[str]:
        return coerce_str_list(v)


class GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    plan_title: str = Field(default="", max_length=512)
    summary: str = ""
    operations: list[GeneratedOperation] = Field(min_length=1)
    inspection_plan: list[InspectionPlanItem] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
