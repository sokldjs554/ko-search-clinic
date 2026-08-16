"""처방 IR과 분석기 설정의 스키마 검증 테스트."""

import pytest
from pydantic import ValidationError

from searchclinic.analysis.config import (
    AnalyzerConfig,
    CompoundExpansion,
    SynonymGroup,
    UserWord,
)
from searchclinic.patch.ir import Prescription


def test_empty_prescription_rejected():
    with pytest.raises(ValidationError, match="패치가 하나도 없다"):
        Prescription(
            target_query="q", diagnosis_family="spelling_variant",
            reasoning="패치 없이 제출하는 잘못된 처방.",
        )


def test_compound_parts_must_reconstruct():
    with pytest.raises(ValidationError, match="이어 붙이면"):
        CompoundExpansion(word="물티슈", parts=["물", "휴지"])


def test_synonym_group_needs_two_distinct_terms():
    with pytest.raises(ValidationError):
        SynonymGroup(terms=["케이크"])
    with pytest.raises(ValidationError, match="중복"):
        SynonymGroup(terms=["케이크", "케이크"])


def test_user_word_no_space():
    with pytest.raises(ValidationError, match="공백"):
        UserWord(form="물 티슈")


def test_config_rejects_duplicate_user_word():
    cfg = AnalyzerConfig(user_words=[UserWord(form="아답터")])
    with pytest.raises(ValueError, match="이미 등록된"):
        cfg.copy_with(user_word=UserWord(form="아답터"))


def test_config_rejects_overlapping_synonym_groups():
    cfg = AnalyzerConfig(synonym_groups=[SynonymGroup(terms=["케이크", "케잌"])])
    with pytest.raises(ValueError, match="이미 다른 동의어 그룹"):
        cfg.copy_with(synonym_group=SynonymGroup(terms=["케잌", "케익"]))


def test_copy_with_immutability():
    base = AnalyzerConfig()
    patched = base.copy_with(user_word=UserWord(form="아답터"))
    assert not base.user_words
    assert len(patched.user_words) == 1


def test_prescription_patch_kinds_and_summary():
    rx = Prescription(
        target_query="아답터", diagnosis_family="garbage_split",
        reasoning="사전 등록과 동의어 연결이 함께 필요한 복합 처방.",
        user_words=[{"form": "아답터"}],
        synonym_groups=[{"terms": ["어댑터", "아답터"]}],
    )
    assert rx.patch_kinds == ("user_word", "synonym")
    assert "사전등록(아답터)" in rx.summary()
    assert "동의어(어댑터 = 아답터)" in rx.summary()


def test_apply_to_produces_new_config():
    rx = Prescription(
        target_query="티슈", diagnosis_family="compound_locked",
        reasoning="물티슈 분해 확장 적용 검증.",
        compound_expansions=[{"word": "물티슈", "parts": ["물", "티슈"]}],
    )
    base = AnalyzerConfig()
    new = rx.apply_to(base)
    assert not base.compound_expansions
    assert new.compound_expansions[0].word == "물티슈"
