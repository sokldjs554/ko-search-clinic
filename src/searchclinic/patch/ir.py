"""처방(Prescription) — 의사가 제출하는 타입 있는 패치 묶음.

LLM이 "동의어를 추가하세요" 같은 산문을 내면 검증도 적용도 롤백도 불가능하다.
처방은 pydantic 모델이어야 한다:

- 스키마 위반(빈 그룹, 재구성 안 되는 분해 규칙)은 **제출 시점에** 거부된다
- 하나의 처방이 여러 패치를 담을 수 있다 — 아답터처럼 사용자 사전 등록과
  동의어 연결이 **함께** 있어야만 동작하는 복합 처방이 실제로 존재한다
- 처방 전체가 하나의 단위로 게이트를 통과하거나 기각된다
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from searchclinic.analysis.config import (
    AnalyzerConfig,
    CompoundExpansion,
    SynonymGroup,
    UserWord,
)

PATCH_KINDS = ("user_word", "synonym", "compound_expansion")


class Prescription(BaseModel):
    """진료 1건의 산출물: 진단 + 패치 묶음."""

    target_query: str = Field(description="치유하려는 실패 질의")
    diagnosis_family: str = Field(
        description=(
            "진단한 실패 계열: spelling_variant | cross_script | synonym_gap "
            "| compound_locked | garbage_split"
        )
    )
    reasoning: str = Field(min_length=10, description="증거에 기반한 진단 근거")
    user_words: list[UserWord] = Field(default_factory=list)
    synonym_groups: list[SynonymGroup] = Field(default_factory=list)
    compound_expansions: list[CompoundExpansion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_empty(self) -> "Prescription":
        if not (self.user_words or self.synonym_groups or self.compound_expansions):
            raise ValueError("처방에 패치가 하나도 없다")
        return self

    @property
    def patch_kinds(self) -> tuple[str, ...]:
        kinds = []
        if self.user_words:
            kinds.append("user_word")
        if self.synonym_groups:
            kinds.append("synonym")
        if self.compound_expansions:
            kinds.append("compound_expansion")
        return tuple(kinds)

    def apply_to(self, config: AnalyzerConfig) -> AnalyzerConfig:
        """설정에 처방을 적용한 새 설정을 반환한다 (원본 불변)."""
        cfg = config
        for w in self.user_words:
            cfg = cfg.copy_with(user_word=w)
        for g in self.synonym_groups:
            cfg = cfg.copy_with(synonym_group=g)
        for c in self.compound_expansions:
            cfg = cfg.copy_with(compound_expansion=c)
        return cfg

    def summary(self) -> str:
        parts = []
        for w in self.user_words:
            parts.append(f"사전등록({w.form})")
        for g in self.synonym_groups:
            parts.append(f"동의어({' = '.join(g.terms)})")
        for c in self.compound_expansions:
            parts.append(f"분해확장({c.word} → {'+'.join(c.parts)})")
        return " + ".join(parts)
