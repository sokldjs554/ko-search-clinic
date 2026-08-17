"""청킹과 전처리 — 조각내면서 무엇을 잃지 않아야 하는가.

청킹은 "자르는 일"처럼 보이지만 실제로 지켜야 할 것은 **잃지 않는 것**이다.
문서를 잃거나, 문장을 반토막 내거나, 검색어가 되는 식별자를 씻어내면
자르지 않느니만 못하다.
"""

import pytest

from searchclinic.corpus import failing_queries
from searchclinic.rag.chunker import (
    DEFAULT_MAX_CHARS,
    chunk_document,
    chunk_knowledge,
    normalize,
    split_text,
)
from searchclinic.rag.knowledge import load_knowledge

LONG = (
    "## 첫 번째 섹션\n"
    + "분석 체인의 순서를 알아야 진단이 가능하다. " * 12
    + "\n\n## 두 번째 섹션\n"
    + "사전 등록이 동의어보다 먼저여야 한다. " * 12
)


# --------------------------------------------------------------- 전처리

def test_normalize_keeps_identifiers_intact():
    """`user_dictionary_rules` 같은 식별자가 이 도메인의 핵심 검색어다.

    기호를 씻어내면 가장 중요한 검색어가 사라진다 — 과한 전처리는 해롭다.
    """
    text = "설정은 user_dictionary_rules 와 decompound_mode: mixed 를 쓴다."
    assert "user_dictionary_rules" in normalize(text)
    assert "decompound_mode: mixed" in normalize(text)


def test_normalize_preserves_paragraph_breaks():
    """문단 경계가 사라지면 1순위 분할 기준이 없어진다."""
    assert "\n\n" in normalize("첫 문단.\n\n\n\n둘째 문단.")


def test_normalize_strips_zero_width_characters():
    assert normalize("어댑​터") == "어댑터"


# --------------------------------------------------------------- 분할

def test_short_text_is_not_split():
    assert split_text("짧은 문서다.") == ["짧은 문서다."]


def test_empty_text_gives_nothing():
    assert split_text("   \n  ") == []


@pytest.mark.parametrize("max_chars", [120, 200, 400])
def test_pieces_respect_the_limit(max_chars):
    """상한을 넘는 조각이 있으면 청킹이 목적을 달성하지 못한 것이다."""
    pieces = split_text(LONG, max_chars=max_chars, overlap=0)
    assert pieces and all(len(p) <= max_chars for p in pieces)


def test_split_does_not_cut_mid_sentence():
    """문장 한복판에서 끊긴 조각은 근거로도 검색어로도 못 쓴다."""
    text = " ".join(f"{i}번째 문장이 여기에 있다." for i in range(40))
    for piece in split_text(text, max_chars=200, overlap=0):
        assert piece.endswith("다.") or piece.endswith("다")


def test_overlap_carries_context_forward():
    """경계에서 앞 문맥이 끊기면 조각 하나만 읽고는 말이 안 된다."""
    without = split_text(LONG, max_chars=200, overlap=0)
    with_overlap = split_text(LONG, max_chars=200, overlap=60)
    assert len(with_overlap) == len(without)
    assert len(with_overlap[1]) > len(without[1])


def test_overlap_zero_changes_nothing():
    assert split_text(LONG, max_chars=200, overlap=0) == split_text(LONG, max_chars=200, overlap=0)


# --------------------------------------------------------------- 문서

def test_section_headers_become_chunk_headings():
    chunks = chunk_document("D1", LONG, max_chars=200)
    assert {"첫 번째 섹션", "두 번째 섹션"} <= {c.heading for c in chunks}


def test_chunk_ids_are_unique_and_ordered():
    chunks = chunk_document("D1", LONG, max_chars=150)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_chunk_keeps_its_source_document():
    assert all(c.doc_id == "D1" for c in chunk_document("D1", LONG, max_chars=150))


def test_heading_only_document_still_produces_a_chunk():
    """제목 줄에 본문이 붙은 문서가 **조용히 사라지면** 안 된다.

    실측 실패: 지식베이스 헬퍼가 개행을 뭉개면서 `## 제목`과 본문이 한 줄이
    됐고, 청커가 그 줄 전체를 제목으로 읽어 본문을 비웠다. 긴 문서 3건이
    색인에서 통째로 사라졌는데, 검색이 안 되는데 이유를 알 수 없는 최악의
    실패다.
    """
    chunks = chunk_document("D1", "## 제목에 본문이 그대로 붙어 있는 문서다.", max_chars=200)
    assert chunks
    assert "본문이 그대로 붙어" in " ".join(c.display for c in chunks)


def test_empty_document_gives_no_chunk():
    assert chunk_document("D1", "  ") == []


# ------------------------------------------------------- 지식베이스와의 계약

def test_no_knowledge_document_is_lost():
    """어떤 청크 크기에서도 문서 하나가 통째로 빠지면 안 된다."""
    docs = load_knowledge()
    for max_chars in (150, 200, 300, 400, 600):
        chunks = chunk_knowledge(docs, max_chars=max_chars, overlap=int(max_chars * 0.2))
        missing = {d.doc_id for d in docs} - {c.doc_id for c in chunks}
        assert not missing, f"{max_chars}자에서 사라진 문서: {missing}"


def test_knowledge_body_keeps_its_line_structure():
    """헬퍼가 개행을 뭉개면 섹션·문단 경계가 사라져 청킹이 무의미해진다."""
    multiline = [d for d in load_knowledge() if "\n" in d.body]
    assert multiline, "줄 구조를 가진 문서가 하나도 없다 — 헬퍼가 뭉갠 것이다"


def test_knowledge_has_documents_long_enough_to_chunk():
    """전부 짧으면 '청킹이 차이를 안 만든다'가 청킹의 성질이 아니라
    코퍼스의 성질이 된다 — 그 측정으로는 아무 말도 할 수 없다."""
    assert max(len(d.body) for d in load_knowledge()) > DEFAULT_MAX_CHARS


def test_chunking_never_leaks_evalset_queries():
    """조각내는 과정에서 평가셋 질의가 만들어지면 정답을 흘리는 것이다."""
    corpus = "\n".join(c.display for c in chunk_knowledge(load_knowledge(), max_chars=200))
    assert not [q.query for q in failing_queries() if q.query in corpus]
