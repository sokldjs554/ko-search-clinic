"""분석기 설정 — 패치가 누적되는 대상.

검색 품질 패치는 코드가 아니라 **설정**을 바꾼다. 사용자 사전 항목,
동의어 그룹, 복합어 분해 규칙 세 가지가 전부다. 설정은 pydantic으로
직렬화되므로 버전 관리·롤백·Elasticsearch 렌더링이 모두 이 타입 하나로
가능하다.

세 가지 패치 유형이 실제 한국어 검색 실패의 서로 다른 형태에 대응한다:

| 유형              | 고치는 실패                                  | ES 대응물                        |
|-------------------|----------------------------------------------|----------------------------------|
| UserWord          | 분석기가 단어를 쓰레기로 쪼갬 (아답터→아/답/터) | user_dictionary_rules            |
| SynonymGroup      | 표기 변형·유의어로 토큰 단절 (케잌↔케이크)     | synonym filter                   |
| CompoundExpansion | 한 덩어리 복합어를 부분어로 못 찾음 (물티슈↛티슈) | user_dictionary + decompound mixed |
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class UserWord(BaseModel):
    """분석기에 강제 등록하는 단어. 쓰레기 분해를 막는다."""

    form: str = Field(min_length=2, description="등록할 표면형 (예: 아답터)")
    tag: str = Field(default="NNP", description="품사 태그. 보통 고유명사 NNP")

    @field_validator("form")
    @classmethod
    def _no_space(cls, v: str) -> str:
        if " " in v:
            raise ValueError("사용자 사전 항목에 공백이 올 수 없다")
        return v


class SynonymGroup(BaseModel):
    """서로 같은 것으로 취급할 토큰 묶음. 첫 항목이 대표형(canonical)이다.

    색인·질의 양쪽에서 그룹 구성원을 대표형으로 정규화한다 —
    Elasticsearch의 index-time synonym filter와 같은 방식이다.
    """

    terms: list[str] = Field(min_length=2, description="동의어 목록. terms[0]이 대표형")

    @field_validator("terms")
    @classmethod
    def _distinct_and_clean(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v]
        if any(not t or " " in t for t in cleaned):
            raise ValueError("동의어 항목은 공백 없는 단일 토큰이어야 한다")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("동의어 그룹에 중복 항목이 있다")
        return cleaned

    @property
    def canonical(self) -> str:
        return self.terms[0]


class CompoundExpansion(BaseModel):
    """복합어를 색인·질의 시 부분어로도 확장한다.

    Kiwi가 '물티슈'를 한 토큰으로 유지하면 질의 '티슈'로는 영원히 찾을 수
    없다. 이 규칙은 '물티슈'가 나올 때 [물티슈, 물, 티슈]를 함께 방출한다 —
    nori의 decompound_mode=mixed와 같은 의미다.
    """

    word: str = Field(min_length=2, description="확장할 복합어 (예: 물티슈)")
    parts: list[str] = Field(min_length=2, description="부분어 목록 (예: [물, 티슈])")

    @model_validator(mode="after")
    def _parts_reconstruct_word(self) -> "CompoundExpansion":
        if "".join(self.parts) != self.word:
            raise ValueError(
                f"부분어를 이어 붙이면 원어가 돼야 한다: "
                f"{'+'.join(self.parts)} ≠ {self.word}"
            )
        if any(len(p) < 1 for p in self.parts):
            raise ValueError("빈 부분어는 허용되지 않는다")
        return self


class AnalyzerConfig(BaseModel):
    """분석기 전체 설정. 패치가 누적되는 단위이며 그대로 직렬화된다."""

    user_words: list[UserWord] = Field(default_factory=list)
    synonym_groups: list[SynonymGroup] = Field(default_factory=list)
    compound_expansions: list[CompoundExpansion] = Field(default_factory=list)

    def copy_with(
        self,
        user_word: UserWord | None = None,
        synonym_group: SynonymGroup | None = None,
        compound_expansion: CompoundExpansion | None = None,
    ) -> "AnalyzerConfig":
        """패치 하나를 더한 새 설정을 반환한다 (원본 불변 — 롤백은 그냥 원본 사용)."""
        cfg = self.model_copy(deep=True)
        if user_word is not None:
            if any(w.form == user_word.form for w in cfg.user_words):
                raise ValueError(f"이미 등록된 사용자 사전 항목: {user_word.form}")
            cfg.user_words.append(user_word)
        if synonym_group is not None:
            existing = {t for g in cfg.synonym_groups for t in g.terms}
            overlap = existing & set(synonym_group.terms)
            if overlap:
                raise ValueError(f"이미 다른 동의어 그룹에 속한 항목: {sorted(overlap)}")
            cfg.synonym_groups.append(synonym_group)
        if compound_expansion is not None:
            if any(c.word == compound_expansion.word for c in cfg.compound_expansions):
                raise ValueError(f"이미 등록된 분해 규칙: {compound_expansion.word}")
            cfg.compound_expansions.append(compound_expansion)
        return cfg

    def describe(self) -> str:
        parts = []
        if self.user_words:
            parts.append(f"사용자사전 {len(self.user_words)}")
        if self.synonym_groups:
            parts.append(f"동의어그룹 {len(self.synonym_groups)}")
        if self.compound_expansions:
            parts.append(f"분해규칙 {len(self.compound_expansions)}")
        return " · ".join(parts) or "(빈 설정)"
