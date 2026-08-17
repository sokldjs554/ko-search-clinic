"""규모 계층 — 합성·레이크·로그 마이닝·규모 실험.

무거운 것(Spark, 5만 건 색인)은 기본 실행에서 뺀다. `-m slow`로 켠다.
CI에서 20분 걸리는 테스트는 사람들이 CI를 끄게 만든다.
"""

import pytest

from searchclinic.corpus import failing_queries, load_catalog, load_evalset
from searchclinic.index.engine import SearchEngine
from searchclinic.scale.benchmark import MINIMAL, OVERBROAD, measure_at_scale
from searchclinic.scale.generate import synthesize_catalog, synthesize_query_log
from searchclinic.scale.lake import (
    lake_stats,
    read_catalog,
    write_catalog,
    write_query_log,
)
from searchclinic.scale.mine import mine_candidates, mine_with_duckdb

pytest.importorskip("pyarrow", reason="규모 계층은 선택 의존성이다")


# --------------------------------------------------------------- 생성

def test_generation_is_deterministic():
    """재현되지 않는 규모 실험 결과로는 아무 말도 할 수 없다."""
    a = synthesize_catalog(500, seed=7)
    b = synthesize_catalog(500, seed=7)
    assert [d.doc_id for d in a] == [d.doc_id for d in b]
    assert [d.name for d in a] == [d.name for d in b]


def test_different_seed_gives_different_corpus():
    a = synthesize_catalog(500, seed=7)
    b = synthesize_catalog(500, seed=8)
    assert [d.name for d in a] != [d.name for d in b]


def test_synthetic_corpus_keeps_the_original_catalog():
    """원본을 빼면 실패 질의의 정답 문서가 사라져 평가가 통째로 무의미해진다."""
    original = {d.doc_id for d in load_catalog()}
    grown = {d.doc_id for d in synthesize_catalog(1000, seed=7)}
    assert original <= grown


def test_synthetic_doc_ids_are_unique():
    docs = synthesize_catalog(2000, seed=7)
    ids = [d.doc_id for d in docs]
    assert len(ids) == len(set(ids))


def test_synthetic_documents_never_match_a_failing_query():
    """합성 문서가 실패 질의를 새로 매칭하면 계열이 무너진다.

    "0건이어야 한다"가 아니라 **"합성 문서가 새 매칭을 만들면 안 된다"**가
    맞는 불변식이다. 원본 코퍼스에서도 `블루투스 스피커`는 0건이 아니라
    `스피커` 문서를 잡는다 — 못 잡는 것은 블루투스 문서 쪽이다. 그 구분을
    놓치면 이 테스트가 엉뚱한 것을 지킨다.
    """
    engine = SearchEngine(synthesize_catalog(3000, seed=7))
    for eq in failing_queries():
        synthetic = [h.doc_id for h in engine.search(eq.query, k=20) if h.doc_id.startswith("S")]
        assert not synthetic, f"{eq.query}가 합성 문서 {synthetic}를 매칭했다"


def test_failing_queries_keep_their_scores_at_scale():
    """규모가 커져도 실패 질의의 nDCG가 오르면 안 된다 — 실패가 유지되어야 한다."""
    from searchclinic.evaluation.metrics import evaluate_query

    small = SearchEngine(load_catalog())
    big = SearchEngine(synthesize_catalog(3000, seed=7))
    for eq in failing_queries():
        assert evaluate_query(big, eq).ndcg <= evaluate_query(small, eq).ndcg + 1e-9


def test_query_log_never_claims_a_click_on_zero_results():
    """로그가 스스로 모순되면 그 로그로 뽑은 후보를 믿을 수 없다."""
    rows = synthesize_query_log(5000, seed=7)
    assert not [r for r in rows if r.n_results == 0 and r.clicked]


def test_query_log_contains_failing_queries():
    rows = synthesize_query_log(5000, seed=7)
    logged = {r.query for r in rows}
    assert logged & {q.query for q in failing_queries()}


# ----------------------------------------------------------------- 레이크

def test_catalog_roundtrip(tmp_path):
    docs = synthesize_catalog(300, seed=7)
    write_catalog(docs, tmp_path)
    back = read_catalog(tmp_path)
    assert [d.doc_id for d in back] == [d.doc_id for d in docs]
    assert back[0].name == docs[0].name  # 한글이 깨지지 않는다


def test_log_is_partitioned_by_date(tmp_path):
    """기간으로 자르는 집계가 파일 자체를 건너뛰려면 날짜로 갈려 있어야 한다."""
    write_query_log(synthesize_query_log(2000, seed=7, days=5), tmp_path)
    stats = lake_stats(tmp_path)
    assert len(stats["log_partitions"]) == 5
    assert all(p.startswith("ts=2026-") for p in stats["log_partitions"])


def test_parquet_is_smaller_than_raw_text(tmp_path):
    """열 기반 + 사전 인코딩이 실제로 압축되는지 — 레이크를 쓰는 이유의 절반."""
    rows = synthesize_query_log(20_000, seed=7)
    write_query_log(rows, tmp_path)
    raw = sum(len(r.ts) + len(r.query) + 8 for r in rows)
    assert lake_stats(tmp_path)["bytes"] < raw / 2


# ------------------------------------------------------------ 로그 마이닝

@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    root = tmp_path_factory.mktemp("lake")
    write_query_log(synthesize_query_log(50_000, seed=7), root)
    return root


def test_candidates_are_ranked_by_zero_result_volume(lake):
    """고쳤을 때 영향을 받는 검색 횟수가 우선순위여야 한다."""
    candidates = mine_with_duckdb(lake, limit=10)
    assert candidates
    volumes = [c.zero_results for c in candidates]
    assert volumes == sorted(volumes, reverse=True)


def test_candidates_surface_real_failing_queries(lake):
    top = {c.query for c in mine_with_duckdb(lake, limit=10)}
    assert top & {q.query for q in failing_queries()}


def test_rare_queries_are_filtered_out(lake):
    """한 번 검색된 오타까지 진료하면 사전이 쓰레기로 찬다."""
    assert all(c.volume >= 5 for c in mine_with_duckdb(lake, limit=50, min_volume=5))


def test_every_candidate_actually_had_zero_results(lake):
    assert all(c.zero_results > 0 for c in mine_with_duckdb(lake, limit=20))


def test_unknown_engine_is_rejected(lake):
    with pytest.raises(ValueError, match="알 수 없는 엔진"):
        mine_candidates(lake, engine="hadoop")


@pytest.mark.slow
def test_spark_and_duckdb_agree(lake):
    """엔진을 갈아탔는데 답이 달라지면 둘 중 하나는 틀린 것이다."""
    pytest.importorskip("pyspark")
    duck = mine_candidates(lake, engine="duckdb", limit=10)
    spark = mine_candidates(lake, engine="spark", limit=10)
    assert [(c.query, c.volume, c.zero_results) for c in duck] == [
        (c.query, c.volume, c.zero_results) for c in spark
    ]


# ----------------------------------------------------------------- 규모

def test_gate_verdicts_hold_at_a_small_scale():
    """규모가 커져도 과잉은 기각, 최소는 채택 — 게이트 보증의 핵심."""
    point = measure_at_scale(2000)
    assert point.overbroad_accepted is False
    assert point.minimal_accepted is True
    assert point.verdicts_hold


def test_fan_documents_grow_with_scale():
    """오염 함정의 밀도가 실제로 커지는지 — 커지지 않으면 실험이 무의미하다."""
    small = measure_at_scale(500)
    big = measure_at_scale(5000)
    assert big.fan_doc_frequency > small.fan_doc_frequency


def test_benchmark_prescriptions_target_an_eval_query():
    """평가셋에 없는 질의를 표적으로 삼으면 게이트가 예외를 던진다."""
    known = {q.query for q in load_evalset()}
    assert OVERBROAD.target_query in known
    assert MINIMAL.target_query in known


@pytest.mark.slow
def test_gate_cost_grows_roughly_linearly():
    """비용이 규모에 선형이라는 리포트의 주장이 참인지."""
    small = measure_at_scale(5_000)
    big = measure_at_scale(20_000)
    ratio = big.gate_seconds / max(small.gate_seconds, 1e-6)
    assert 2.0 < ratio < 8.0  # 4배 문서 → 대략 4배 (여유 있게)
