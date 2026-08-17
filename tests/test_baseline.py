"""CI 품질 게이트 — 저장소가 바뀌는 경로를 실제로 막는가.

진료 게이트는 **처방**을 본다. 이 게이트는 **커밋**을 본다. 그래서 여기서
확인해야 할 것은 "회귀를 잡는가"만이 아니라, **검사를 무력화하는 방법이
없는가**이다. 특히 실패하는 질의를 평가셋에서 지워 초록불을 만드는 길이
열려 있으면 이 검사는 있으나 마나다.
"""

import json

import pytest

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.evaluation.baseline import (
    EPSILON,
    compare,
    load_baseline,
    measure,
    write_baseline,
)
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.gate import EPSILON as GATE_EPSILON


@pytest.fixture(scope="module")
def engine():
    return SearchEngine(load_catalog())


@pytest.fixture(scope="module")
def evalset():
    return load_evalset()


@pytest.fixture(scope="module")
def baseline(engine, evalset):
    return measure(engine, evalset)


def _shift(baseline: dict, query: str, metric: str, value: float) -> dict:
    """기준선 한 칸만 바꾼 사본. 코퍼스를 건드리지 않고 대조 로직만 시험한다."""
    clone = json.loads(json.dumps(baseline))
    clone["queries"][query][metric] = value
    return clone


# ----------------------------------------------------------- 기준선 자체

def test_baseline_covers_every_eval_query(baseline, evalset):
    assert set(baseline["queries"]) == {q.query for q in evalset}


def test_epsilon_matches_the_prescription_gate():
    """서로 다른 값이면 '게이트는 통과했는데 CI가 막는' 상태가 생긴다.

    그 순간 둘 중 하나는 아무도 안 믿게 되고, 안 믿는 검사는 꺼진다.
    """
    assert EPSILON == GATE_EPSILON


def test_write_and_load_roundtrip(engine, evalset, tmp_path):
    path = tmp_path / "BASELINE.json"
    written = write_baseline(engine, evalset, path)
    assert load_baseline(path) == written
    assert "한국어" in path.read_text(encoding="utf-8") or "프라이팬" in path.read_text(
        encoding="utf-8"
    )  # ensure_ascii=False — 사람이 읽을 수 있어야 리뷰가 된다


# --------------------------------------------------------------- 대조

def test_unchanged_repo_passes(engine, evalset, baseline):
    report = compare(engine, evalset, baseline)
    assert report.ok
    assert not report.regressions and not report.missing


def test_regression_is_caught(engine, evalset, baseline):
    """기준선이 더 높았다면 지금은 회귀다.

    `티슈`는 치유 전 nDCG가 0인 실패 질의라, 기준선을 1.0으로 올리면
    현재 상태가 확실히 그 아래가 된다.
    """
    assert baseline["queries"]["티슈"]["ndcg"] < 1.0 - EPSILON  # 전제 확인
    inflated = _shift(baseline, "티슈", "ndcg", 1.0)

    report = compare(engine, evalset, inflated)
    assert not report.ok
    assert [(d.query, d.metric) for d in report.regressions] == [("티슈", "ndcg")]
    assert "회귀" in report.summary()


def test_improvement_is_reported_but_does_not_fail(engine, evalset, baseline):
    """좋아진 것을 막으면 아무도 이 검사를 안 켠다."""
    lowered = _shift(baseline, "프라이팬", "ndcg", 0.0)
    report = compare(engine, evalset, lowered)
    assert report.ok
    assert any(d.query == "프라이팬" for d in report.improvements)


def test_change_within_epsilon_is_not_a_regression(engine, evalset, baseline):
    """문서빈도 변화에 의한 미세한 흔들림까지 막으면 빨간불이 상시가 된다."""
    nudged = _shift(
        baseline, "프라이팬", "ndcg", baseline["queries"]["프라이팬"]["ndcg"] + EPSILON / 2
    )
    assert compare(engine, evalset, nudged).ok


def test_deleting_a_query_cannot_turn_the_build_green(engine, evalset, baseline):
    """실패 질의를 평가셋에서 지워 초록불을 만드는 길이 열려 있으면 검사가 무의미하다."""
    smaller = [q for q in evalset if q.query != "아답터"]
    report = compare(SearchEngine(load_catalog()), smaller, baseline)

    assert not report.ok
    assert "아답터" in report.missing
    assert "사라진 질의" in report.summary()


def test_new_query_is_flagged_without_failing(engine, evalset, baseline):
    """질의를 추가하는 것은 정상 작업이다 — 다만 기준선 갱신이 필요하다고 알린다."""
    trimmed = json.loads(json.dumps(baseline))
    removed = trimmed["queries"].pop("아답터")
    assert removed is not None

    report = compare(engine, evalset, trimmed)
    assert report.ok
    assert "아답터" in report.added
    assert "기준선" in report.markdown()


# --------------------------------------------------------------- 출력

def test_markdown_marks_pass_and_fail(engine, evalset, baseline):
    assert "✅ 통과" in compare(engine, evalset, baseline).markdown()

    broken = _shift(baseline, "티슈", "ndcg", 1.0)
    md = compare(engine, evalset, broken).markdown()
    assert "❌ 회귀" in md
    assert "| 티슈 | ndcg |" in md  # 표에 실제 행이 있어야 읽을 값이 된다


def test_drift_delta_sign(engine, evalset, baseline):
    broken = _shift(baseline, "티슈", "ndcg", 1.0)
    drift = next(d for d in compare(engine, evalset, broken).regressions if d.query == "티슈")
    assert drift.delta < 0
    assert "↓" in drift.describe()


# ---------------------------------------------------- 커밋된 기준선과의 계약

def test_committed_baseline_matches_the_repository():
    """저장소에 커밋된 기준선이 지금 코드의 실측과 같아야 한다.

    이것이 어긋난 채로 커밋되면 CI가 첫 푸시부터 빨간불이 되고, 그러면
    사람들은 검사를 끄지 기준선을 고치지 않는다.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "docs" / "BASELINE.json"
    if not path.exists():
        pytest.skip("기준선 미생성")

    report = compare(SearchEngine(load_catalog()), load_evalset(), load_baseline(path))
    assert report.ok, report.summary()
    assert not report.added, f"기준선에 없는 질의: {report.added}"
