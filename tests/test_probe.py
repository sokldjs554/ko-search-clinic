"""분리 검사 자체가 옳은지 시험한다 — 통제된 벡터로.

이 검사는 "벡터를 쓰지 말자"는 결론의 근거다. 근거를 만드는 자가
틀렸으면 결론도 틀린다. 그래서 **가를 수 있는 경우에는 가릴 수 있다고
답하는지**부터 확인한다 (항상 "분리 불가"를 뱉는 검사는 쓸모가 없다).
"""

import math

import pytest

from searchclinic.analysis.probe import (
    LINK_PAIRS,
    NOLINK_PAIRS,
    UNHEALED,
    hub_scores,
    rank_of_answer,
    render_probe_markdown,
    score_pairs,
    separability,
)
from searchclinic.analysis.vectors import CachedVectors, load_vectors_if_available


def _unit(*xs: float) -> list[float]:
    n = math.sqrt(sum(x * x for x in xs))
    return [x / n for x in xs]


def _pairs(scores: list[float]) -> list[tuple[str, str, float | None]]:
    return [(f"a{i}", f"b{i}", s) for i, s in enumerate(scores)]


# ------------------------------------------------------- 분리 판정

def test_clean_split_is_reported_when_it_exists():
    """가를 수 있으면 가릴 수 있다고 답해야 한다 — 검사의 최소 조건."""
    sep = separability(_pairs([0.90, 0.85, 0.80]), _pairs([0.40, 0.30]))
    assert sep["clean_split"] is True
    assert sep["best_accuracy"] == 1.0


def test_overlap_is_reported_when_distributions_cross():
    sep = separability(_pairs([0.90, 0.40]), _pairs([0.80, 0.50]))
    assert sep["clean_split"] is False
    assert sep["overlap_low"] == pytest.approx(0.50)
    assert sep["overlap_high"] == pytest.approx(0.80)


def test_touching_distributions_are_not_a_clean_split():
    """정답 최저와 쓰레기 최고가 같으면 그 값을 어느 쪽으로 보내도 하나가 틀린다."""
    assert separability(_pairs([0.7, 0.9]), _pairs([0.7, 0.3]))["clean_split"] is False


def test_best_threshold_maximizes_correct_pairs():
    sep = separability(_pairs([0.9, 0.8, 0.2]), _pairs([0.7, 0.1]))
    # 0.2에서도 0.8에서도 4/5로 동점이다(0.2: 정답 3 + 쓰레기 1, 0.8: 2 + 2).
    # 동점이면 쓰레기를 덜 들이는 **높은 쪽**을 고른다.
    assert sep["best_correct"] == 4
    assert sep["best_threshold"] == pytest.approx(0.8)


def test_useless_signal_does_not_beat_the_trivial_baseline():
    """정답이 쓰레기 사이에 끼면 '전부 채택'보다 나을 수 없다 — 그 사실을 말해야 한다.

    정답(0.6, 0.4)이 쓰레기(0.9 / 0.5 / 0.1) **위아래 양쪽에 끼어** 있다.
    이러면 선을 어디에 그어도 위쪽 쓰레기나 아래쪽 쓰레기 중 하나가 남는다.
    실측 캐시가 정확히 이 모양이었다(최적 10/18 = 바닥선 10/18).
    """
    sep = separability(_pairs([0.6, 0.4]), _pairs([0.9, 0.5, 0.1]))
    assert sep["best_correct"] == sep["baseline_correct"] == 3
    assert sep["beats_baseline"] is False


def test_real_signal_beats_the_trivial_baseline():
    """반대로 신호가 살아 있으면 바닥선을 넘는다고 답해야 한다."""
    sep = separability(_pairs([0.9, 0.8]), _pairs([0.2, 0.1]))
    assert sep["beats_baseline"] is True


def test_ties_resolve_to_the_stricter_threshold():
    """느슨한 쪽을 고르면 '이 임계값이면 된다'가 쓰레기를 통과시키는 값이 된다."""
    sep = separability(_pairs([0.9, 0.5]), _pairs([0.4, 0.1]))
    assert sep["best_correct"] == 4
    assert sep["best_threshold"] == pytest.approx(0.5)  # 0.5도 0.41도 4/4


def test_missing_tokens_make_the_verdict_unavailable_not_false():
    """캐시에 없는 것을 0으로 세면 '분리 불가'가 거짓으로 만들어진다."""
    sep = separability(_pairs([None, None]), _pairs([0.5]))
    assert sep["clean_split"] is False and "reason" in sep
    assert "best_threshold" not in sep


def test_score_pairs_keeps_none_for_unknown_tokens():
    v = CachedVectors({"가": _unit(1.0, 0.0)})
    assert score_pairs(v, [("가", "없음")]) == [("가", "없음", None)]


# ------------------------------------------------------- 허브

def test_hub_scores_rank_the_promiscuous_token_first():
    """모두와 가까운 토큰이 1위여야 한다 — 허브 진단의 정의."""
    v = CachedVectors(
        {
            "허브": _unit(1.0, 1.0, 1.0),
            "가": _unit(1.0, 0.0, 0.0),
            "나": _unit(0.0, 1.0, 0.0),
            "다": _unit(0.0, 0.0, 1.0),
        }
    )
    assert hub_scores(v, ["허브", "가", "나", "다"])[0][0] == "허브"


def test_hub_scores_skip_tokens_absent_from_cache():
    v = CachedVectors({"가": _unit(1.0, 0.0), "나": _unit(0.0, 1.0)})
    assert [t for t, _ in hub_scores(v, ["가", "나", "없음"])] == ["가", "나"]


# ------------------------------------------------------- 순위

def test_rank_of_answer_finds_the_position():
    v = CachedVectors(
        {
            "질의": _unit(1.0, 0.0),
            "가까움": _unit(0.99, 0.14),
            "정답": _unit(0.7, 0.7),
            "멂": _unit(0.0, 1.0),
        }
    )
    rank, head = rank_of_answer(v, "질의", "정답", ["가까움", "정답", "멂"])
    assert rank == 2
    assert head[0][0] == "가까움"


def test_rank_of_answer_is_none_when_answer_not_in_vocabulary():
    """어휘에 없는 것을 '1위'로 답하면 순위 표가 거짓말을 한다."""
    v = CachedVectors({"질의": _unit(1.0, 0.0), "가": _unit(0.0, 1.0)})
    rank, _ = rank_of_answer(v, "질의", "정답", ["가"])
    assert rank is None


# ------------------------------------------------------- 목록의 전제

def test_pair_lists_are_disjoint():
    """같은 쌍이 양쪽에 있으면 어떤 임계값도 100%가 될 수 없다 — 검사가 자멸한다."""
    link = {frozenset(p) for p in LINK_PAIRS}
    nolink = {frozenset(p) for p in NOLINK_PAIRS}
    assert not (link & nolink)


def test_probe_tokens_exist_in_the_committed_cache():
    """커밋된 캐시로 검사가 실제로 돌아야 한다 — 표가 '캐시 없음'으로 차면 무의미하다."""
    vectors = load_vectors_if_available()
    if vectors is None:
        pytest.skip("벡터 캐시 없음")
    needed = {t for p in LINK_PAIRS + NOLINK_PAIRS + UNHEALED for t in p}
    assert not [t for t in needed if t not in vectors]


def test_render_reports_the_measured_negative_result():
    """커밋된 캐시에서 실제로 '분리 불가'가 나오는지 — 문서의 주장과 코드가 같아야 한다."""
    vectors = load_vectors_if_available()
    if vectors is None:
        pytest.skip("벡터 캐시 없음")
    from searchclinic.corpus import load_catalog
    from searchclinic.index.engine import SearchEngine

    md = render_probe_markdown(vectors, sorted(SearchEngine(load_catalog()).vocabulary()))
    assert "분리 불가" in md
    assert "절단선 8 밖" in md  # 정답이 후보 목록 밖이라는 것이 핵심 근거다
