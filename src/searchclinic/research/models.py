"""Observations keep evaluator metadata outside the policy interface."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    query_id: str
    query: str
    split: Literal["train", "dev", "test"]
    result_count: int | None = Field(default=None, ge=0)
    top1_score: float | None = None
    top2_score: float | None = None
    score_margin: float | None = None
    lexical_coverage: float | None = Field(default=None, ge=0, le=1)
    retriever_agreement: float | None = Field(default=None, ge=0, le=1)
    evidence_conflict: bool | None = None
    grounding_score: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float | None = Field(default=None, ge=0)


class RetrievalObservation(PolicyObservation):
    family: str | None = None
    baseline_ndcg: float | None = Field(default=None, ge=0, le=1)
    baseline_recall: float | None = Field(default=None, ge=0, le=1)

    def policy_view(self) -> PolicyObservation:
        return PolicyObservation(**self.model_dump(exclude={
            "family", "baseline_ndcg", "baseline_recall"}))


class Detection(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    failure_probability: float | None = Field(default=None, ge=0, le=1)
    predicted_failure: bool | None = None
    failure_reason_codes: tuple[str, ...] = ()
    calibration_version: str = "rule-v1-uncalibrated"


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_type: Literal["query", "document"]
    source_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_span(self):
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("invalid evidence span offsets")
        return self

    @property
    def evidence_id(self) -> str:
        return f"{self.source_type}:{self.source_id}:{self.start}:{self.end}"
