"""RAG 계층 — 검색이 정직하게 채점되는가.

여기서 지켜야 할 것은 "검색이 잘 되는가"보다 **"잘 된다는 측정이 참인가"**다.
처음 재봤을 때 적중률 100%·MRR 1.000이 나왔는데 전부 거짓이었다 — 모든
계열에 걸린 문서 하나가 어떤 질의에도 정답이 돼서 생긴 값이었다. 그 함정을
테스트가 들고 있어야 다시 빠지지 않는다.
"""

import pytest

from searchclinic.analysis.vectors import load_vectors_if_available
from searchclinic.corpus import failing_queries, load_catalog
from searchclinic.doctor.prompts import (
    MINIMAL_SYSTEM_PROMPT,
    PROMPT_VARIANTS,
    SYSTEM_PROMPT,
    build_brief,
)
from searchclinic.index.engine import SearchEngine
from searchclinic.rag.evaluate import (
    build_retrieval_query,
    discriminative_docs,
    evaluate_retrieval,
)
from searchclinic.rag.knowledge import families_covered, load_knowledge
from searchclinic.rag.retriever import (
    DEFAULT_MODE,
    MODES,
    KnowledgeRetriever,
    render_context,
)


@pytest.fixture(scope="module")
def engine():
    return SearchEngine(load_catalog())


@pytest.fixture(scope="module")
def vectors():
    return load_vectors_if_available()


# ------------------------------------------------------------- 지식베이스

def test_knowledge_ids_are_unique():
    ids = [d.doc_id for d in load_knowledge()]
    assert len(ids) == len(set(ids))


def test_every_failure_family_has_knowledge():
    """계열 하나라도 문서가 없으면 그 계열은 RAG로 도울 방법이 없다."""
    from searchclinic.corpus import failing_queries as fq

    assert {q.family for q in fq()} <= families_covered()


def test_knowledge_does_not_leak_evalset_answers():
    """지식베이스에 평가셋 질의가 그대로 적혀 있으면 정답표다.

    그런 문서로 잰 성적은 검색이 잘 됐다는 뜻이 아니라 답을 흘렸다는 뜻이다.
    """
    corpus = "\n".join(d.text for d in load_knowledge())
    leaked = [q.query for q in failing_queries() if q.query in corpus]
    assert not leaked, f"지식베이스가 평가셋 질의를 그대로 담고 있다: {leaked}"


def test_every_doc_cites_a_source():
    """출처 없는 문장을 근거처럼 읽게 만들면 RAG는 할루시네이션의 도구가 된다."""
    assert all(d.source.strip() for d in load_knowledge())


# --------------------------------------------------------------- 검색 질의

def test_retrieval_query_carries_symptoms_not_answers(engine):
    q = build_retrieval_query("아답터", engine)
    assert "0건" in q and "답" in q and "IC" in q  # 관측 가능한 증상
    assert "garbage_split" not in q  # 정답 계열은 들어가면 안 된다
    assert "사전 등록" not in q  # 처방도 마찬가지


def test_retrieval_query_has_no_family_labels(engine):
    """어떤 질의로도 정답 계열 이름이 새어나가면 안 된다."""
    for eq in failing_queries():
        q = build_retrieval_query(eq.query, engine)
        assert not any(f in q for f in families_covered())


# ----------------------------------------------------------------- 검색

def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="알 수 없는 검색 방식"):
        KnowledgeRetriever(mode="없는방식")


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_returns_at_most_k(mode, vectors):
    hits = KnowledgeRetriever(vectors=vectors, mode=mode).retrieve("검색 0건 분해", k=3)
    assert 0 < len(hits) <= 3


def test_dense_without_cache_degrades_visibly_not_silently():
    """캐시 없이 dense를 부르면 조용히 빈 결과를 내면 안 된다.

    빈 결과를 돌려주면 "RAG를 켜고 돌렸다"는 기록이 거짓이 된다.
    """
    r = KnowledgeRetriever(vectors=None, mode="dense")
    assert r.requested_mode == "dense"
    assert r.mode == "bm25" and r.degraded is True
    assert r.retrieve("검색 0건", k=3)  # 빈 목록이 아니어야 한다


def test_no_degradation_flag_when_cache_present(vectors):
    if vectors is None:
        pytest.skip("벡터 캐시 없음")
    r = KnowledgeRetriever(vectors=vectors, mode="dense")
    assert r.mode == "dense" and r.degraded is False


def test_render_context_includes_source(vectors):
    ctx = render_context(KnowledgeRetriever(vectors=vectors).retrieve("복합어 통짜 색인", k=2))
    assert "출처:" in ctx and "[K0" in ctx


def test_render_context_of_nothing_is_empty():
    assert render_context([]) == ""


# --------------------------------------------------------------- 채점

def test_universal_doc_is_excluded_from_scoring():
    """모든 계열에 걸린 문서는 '어느 계열을 찾았는지'를 가려내지 못한다.

    실측 함정: 이걸 정답에 넣었더니 적중률 100%·MRR 1.000이 나왔고,
    전부 그 문서 하나가 만든 값이었다.
    """
    r = KnowledgeRetriever()
    all_families = families_covered()
    universal = [d for d in r.docs if set(d.families) == all_families]
    assert universal, "이 테스트의 전제 — 모든 계열에 걸린 문서가 실제로 있다"

    scorable_ids = {d.doc_id for d in discriminative_docs(r)}
    assert not (scorable_ids & {d.doc_id for d in universal})


def test_scoring_is_not_trivially_perfect(engine, vectors):
    """채점이 100%를 뱉으면 채점이 고장 났는지부터 의심해야 한다."""
    report = evaluate_retrieval(
        KnowledgeRetriever(vectors=vectors, mode=DEFAULT_MODE), failing_queries(), engine, k=3
    )
    assert report.rows
    assert 0.0 < report.hit_rate < 1.0


def test_recall_and_mrr_are_consistent(engine, vectors):
    """적중이 하나도 없으면 MRR도 0이어야 한다 — 지표끼리 어긋나면 못 믿는다."""
    report = evaluate_retrieval(
        KnowledgeRetriever(vectors=vectors), failing_queries(), engine, k=3
    )
    for row in report.rows:
        assert (row.reciprocal_rank > 0) == row.hit


def test_dense_ranks_the_right_document_first_more_often(engine, vectors):
    """의미 검색은 **1위를 맞히는 데** 강하다 — 문서 설명의 표가 이 관계에 선다.

    처음엔 "dense가 모든 k에서 이긴다"고 적었는데, 긴 문서를 넣자 k=3에서
    BM25가 앞섰다. 코퍼스가 바뀌면 신호의 우열도 바뀐다는 것을 이 테스트가
    잡아냈다. 그래서 지금은 **k=1에서의 우위**만 주장한다 — 그것이 실측이
    지지하는 범위다.
    """
    if vectors is None:
        pytest.skip("벡터 캐시 없음")
    qs = failing_queries()
    dense = evaluate_retrieval(KnowledgeRetriever(vectors=vectors, mode="dense"), qs, engine, k=1)
    bm25 = evaluate_retrieval(KnowledgeRetriever(vectors=vectors, mode="bm25"), qs, engine, k=1)
    assert dense.hit_rate > bm25.hit_rate


def test_default_mode_wins_at_the_default_k(engine, vectors):
    """기본값이 기본 k에서 최선이어야 한다 — 아니면 기본값을 고른 근거가 없다."""
    from searchclinic.rag.retriever import DEFAULT_TOP_K

    qs = failing_queries()
    scores = {
        mode: evaluate_retrieval(
            KnowledgeRetriever(vectors=vectors, mode=mode), qs, engine, k=DEFAULT_TOP_K
        ).hit_rate
        for mode in MODES
    }
    assert scores[DEFAULT_MODE] == max(scores.values()), scores


# --------------------------------------------------------------- 프롬프트

def test_minimal_prompt_drops_the_domain_knowledge():
    """최소 프롬프트에 계열과 처방이 남아 있으면 대조군이 성립하지 않는다."""
    for leaked in ("spelling_variant", "compound_locked", "사전 등록", "최소주의"):
        assert leaked not in MINIMAL_SYSTEM_PROMPT
    assert "spelling_variant" in SYSTEM_PROMPT  # 전체 프롬프트에는 있다


def test_minimal_prompt_keeps_the_procedure():
    """지식은 빼되 절차(제출→게이트→재제출)는 남아야 한다."""
    assert "게이트" in MINIMAL_SYSTEM_PROMPT and "한국어" in MINIMAL_SYSTEM_PROMPT


def test_prompt_variants_registered():
    assert set(PROMPT_VARIANTS) == {"full", "minimal"}


def test_brief_without_knowledge_has_no_reference_section():
    assert "참고 자료" not in build_brief("아답터", 0)


def test_brief_with_knowledge_marks_it_as_general_principle(vectors):
    """검색된 문서를 '이 질의의 답'으로 읽게 하면 오진을 유도한다."""
    ctx = render_context(KnowledgeRetriever(vectors=vectors).retrieve("분해 0건", k=2))
    brief = build_brief("아답터", 0, knowledge=ctx)
    assert "참고 자료" in brief and "일반 원칙" in brief
    assert "K0" in brief
