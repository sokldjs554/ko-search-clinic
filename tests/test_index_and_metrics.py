"""BM25 색인·검색 엔진·지표 테스트."""

import pytest

from searchclinic.corpus import load_catalog
from searchclinic.corpus.evalset import EvalQuery
from searchclinic.evaluation.metrics import evaluate_query
from searchclinic.index.bm25 import BM25Index
from searchclinic.index.engine import SearchEngine


def test_bm25_ranks_higher_tf_first():
    idx = BM25Index()
    idx.build({
        "a": ["케이크", "케이크", "딸기"],
        "b": ["케이크", "포도"],
        "c": ["빵"],
    })
    hits = idx.search(["케이크"])
    assert [h.doc_id for h in hits] == ["a", "b"]


def test_bm25_deterministic_tie_break():
    idx = BM25Index()
    idx.build({"b": ["사과"], "a": ["사과"]})
    hits = idx.search(["사과"])
    assert [h.doc_id for h in hits] == ["a", "b"]  # 동점은 doc_id 사전순


def test_bm25_rare_term_outweighs_common():
    docs = {f"d{i}": ["흔한말", f"고유{i}"] for i in range(10)}
    docs["target"] = ["흔한말", "희귀어"]
    idx = BM25Index()
    idx.build(docs)
    hits = idx.search(["희귀어", "흔한말"])
    assert hits[0].doc_id == "target"
    assert "희귀어" in hits[0].matched_terms


def test_engine_with_config_is_isolated():
    from searchclinic.analysis.config import AnalyzerConfig, SynonymGroup

    engine = SearchEngine(load_catalog())
    patched = engine.with_config(
        AnalyzerConfig(synonym_groups=[SynonymGroup(terms=["프라이팬", "후라이팬"])])
    )
    assert patched.search("후라이팬")  # 새 엔진은 찾는다
    assert not engine.search("후라이팬")  # 원본은 여전히 0건


def test_grep_ignores_spaces():
    engine = SearchEngine(load_catalog())
    # 문서 원문은 "물티슈"인데 공백 섞인 입력으로도 찾아진다
    assert engine.grep_raw("물 티슈")
    assert engine.grep_raw("bluetooth")  # 대소문자 무시


def test_ndcg_perfect_and_zero():
    engine = SearchEngine(load_catalog())
    perfect = evaluate_query(engine, EvalQuery("프라이팬", {"P001": 2, "P002": 2}))
    assert perfect.ndcg == 1.0 and perfect.recall == 1.0
    zero = evaluate_query(engine, EvalQuery("후라이팬", {"P001": 2}))
    assert zero.ndcg == 0.0 and zero.zero_result


def test_precision5_counts_junk():
    """정답이 위에 있어도 상위 5건에 쓰레기가 섞이면 precision@5가 떨어진다."""
    engine = SearchEngine(load_catalog())
    m = evaluate_query(engine, EvalQuery("스피커", {"P033": 2}))
    # 스피커 질의는 P032/P033/P034 세 건을 찾지만 정답은 하나뿐
    assert m.n_results >= 3
    assert m.precision5 == pytest.approx(1 / m.n_results if m.n_results <= 5 else 1 / 5, abs=0.01) or m.precision5 < 1.0


def test_graded_ndcg_orders_by_grade():
    """등급 2 문서가 등급 1보다 위에 있어야 nDCG가 더 높다."""
    engine = SearchEngine(load_catalog())
    # 리모컨: P041(수납함보다 본품이 위) — 등급 반영 확인
    m = evaluate_query(engine, EvalQuery("리모컨", {"P041": 2, "P042": 1}))
    assert m.hits_top[0] == "P041"
    assert m.ndcg == 1.0
