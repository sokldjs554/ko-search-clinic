"""임베딩 유사도 계층 테스트 — 모델 없이 전부 돈다.

실제 모델은 캐시를 만들 때만 필요하고(`clinic build-vectors`), 규칙이
옳은지는 결정적인 가짜 벡터로 고정한다. 모델이 있어야만 도는 테스트는
CI에서 영영 안 돌고, 안 도는 코드는 썩는다.
"""

import json
import math

import pytest

from searchclinic.analysis.vectors import (
    VECTOR_THRESHOLD,
    CachedVectors,
    cosine,
    load_vectors_if_available,
)
from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor import ClinicExecutor, ScriptedDoctor, make_doctor
from searchclinic.doctor.loop import run_doctor_session
from searchclinic.index.engine import SearchEngine


def _unit(*xs: float) -> list[float]:
    n = math.sqrt(sum(x * x for x in xs))
    return [x / n for x in xs]


# 뜻이 같은 것끼리 가깝고, 형태만 닮은 것과는 멀도록 손으로 배치한 벡터.
# 실제 모델 값이 아니라 **규칙을 시험하기 위한 통제된 입력**이다.
FAKE = {
    "블루투스": _unit(1.0, 0.0, 0.0),
    "bluetooth": _unit(0.97, 0.24, 0.0),   # 같은 뜻, 다른 문자 체계
    "스피커": _unit(0.0, 1.0, 0.0),
    "핸드폰": _unit(0.0, 0.0, 1.0),
    "휴대폰": _unit(0.10, 0.0, 0.99),      # 같은 뜻, 같은 문자 체계
    "프라이팬": _unit(0.0, 0.6, 0.8),
    "팬": _unit(0.8, 0.6, 0.0),            # 형태는 겹치나 뜻은 멀어야 한다
}


# --------------------------------------------------------------- 코사인

def test_cosine_basics():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_is_scale_invariant():
    """정규화되지 않은 벡터를 받아도 같은 값이어야 한다."""
    assert cosine([3, 4], [6, 8]) == pytest.approx(1.0)


@pytest.mark.parametrize("a,b", [([], [1]), ([1, 2], [1]), ([0, 0], [1, 1])])
def test_cosine_degenerate_inputs_return_zero(a, b):
    """길이가 다르거나 영벡터면 0 — 예외를 던지면 진료가 통째로 죽는다."""
    assert cosine(a, b) == 0.0


# --------------------------------------------------------------- 캐시

def test_unknown_token_is_none_not_zero():
    """모르는 단어를 0.0으로 답하면 '뜻이 멀다'와 구분되지 않는다."""
    v = CachedVectors(FAKE)
    assert v.similarity("블루투스", "없는단어") is None
    assert v.similarity("없는단어", "블루투스") is None
    assert v.similarity("블루투스", "bluetooth") is not None


def test_save_load_roundtrip_preserves_similarity(tmp_path):
    path = tmp_path / "vectors.json"
    CachedVectors(FAKE, model="fake-model").save(path)
    loaded = CachedVectors.load(path)

    assert loaded.model == "fake-model"
    assert len(loaded) == len(FAKE)
    before = CachedVectors(FAKE).similarity("핸드폰", "휴대폰")
    after = loaded.similarity("핸드폰", "휴대폰")
    assert after == pytest.approx(before, abs=1e-4)


def test_saved_file_is_utf8_and_compact(tmp_path):
    path = tmp_path / "vectors.json"
    CachedVectors(FAKE, model="m").save(path)
    raw = path.read_text(encoding="utf-8")
    assert "블루투스" in raw  # ensure_ascii=False — 한글이 그대로 보인다
    assert json.loads(raw)["dim"] == 3


def test_load_missing_cache_returns_none(tmp_path):
    assert load_vectors_if_available(tmp_path / "없음.json") is None


def test_fake_vectors_separate_meaning_from_form():
    """이 테스트 데이터가 전제를 지키는지부터 확인한다.

    '같은 뜻은 임계값 위, 형태만 닮은 것은 아래'가 깨지면 아래 규칙
    테스트들이 통과해도 아무것도 증명하지 못한다.
    """
    v = CachedVectors(FAKE)
    assert v.similarity("블루투스", "bluetooth") >= VECTOR_THRESHOLD
    assert v.similarity("핸드폰", "휴대폰") >= VECTOR_THRESHOLD
    assert v.similarity("프라이팬", "팬") < VECTOR_THRESHOLD


# --------------------------------------------------------------- 도구

def _executor(vectors=None):
    return ClinicExecutor(
        engine=SearchEngine(load_catalog()), evalset=load_evalset(), vectors=vectors
    )


def test_find_similar_tokens_omits_vector_key_without_cache():
    rows = _executor()._tool_find_similar_tokens("블루투스")["similar"]
    assert rows and all("vector_similarity" not in r for r in rows)


def test_find_similar_tokens_surfaces_cross_script_candidate():
    """자모로만 정렬하면 bluetooth(자모 0.00)가 목록 끝으로 밀려 안 보인다."""
    ex = _executor(CachedVectors(FAKE))
    payload = ex._tool_find_similar_tokens("블루투스", k=8)
    tokens = [r["token"] for r in payload["similar"]]
    assert "bluetooth" in tokens

    row = next(r for r in payload["similar"] if r["token"] == "bluetooth")
    assert row["similarity"] == 0.0  # 자모는 못 넘는다
    assert row["vector_similarity"] >= VECTOR_THRESHOLD


def test_find_similar_tokens_notes_when_term_is_unknown():
    ex = _executor(CachedVectors(FAKE))
    payload = ex._tool_find_similar_tokens("캐시에없는말")
    assert "note" in payload and "벡터 사전에 없어" in payload["note"]


# --------------------------------------------------------------- 규칙

def _similar_row(token, jamo, vec=None):
    row = {"token": token, "similarity": jamo}
    if vec is not None:
        row["vector_similarity"] = vec
    return row


def _doctor_with(similar, probe, use_vectors=True):
    d = ScriptedDoctor(use_vectors=use_vectors)
    d._similar = similar
    d._query = probe
    d._query_tokens = [probe]
    return d


def test_semantic_rule_labels_cross_script():
    """한쪽만 라틴 문자면 영한 혼용이다 — 계열을 틀리면 오진으로 센다."""
    d = _doctor_with([_similar_row("bluetooth", 0.0, 0.95)], "블루투스")
    rx = d._rule_semantic()
    assert rx["diagnosis_family"] == "cross_script"
    assert rx["synonym_groups"][0]["terms"] == ["bluetooth", "블루투스"]


def test_semantic_rule_labels_synonym_gap():
    d = _doctor_with([_similar_row("휴대폰", 0.63, 0.92)], "핸드폰")
    assert d._rule_semantic()["diagnosis_family"] == "synonym_gap"


def test_semantic_rule_ignores_candidates_already_caught_by_jamo():
    """자모가 잡는 표기 변형을 여기서 다시 잡으면 유의어로 오진한다."""
    d = _doctor_with([_similar_row("케이크", 0.67, 0.99)], "케잌")
    assert d._rule_semantic() is None


def test_semantic_rule_respects_threshold():
    d = _doctor_with([_similar_row("팬", 0.30, VECTOR_THRESHOLD - 0.01)], "프라이팬")
    assert d._rule_semantic() is None


def test_semantic_rule_is_off_without_vectors():
    """벡터를 끈 베이스라인은 이 규칙을 아예 쓰지 않는다 — 비교의 전제다."""
    d = _doctor_with([_similar_row("휴대폰", 0.63, 0.92)], "핸드폰", use_vectors=False)
    assert d._rule_semantic() is None


# --------------------------------------------------------------- 엔진

def test_make_doctor_vector_enables_the_rule():
    assert make_doctor("vector").use_vectors is True
    assert make_doctor("scripted").use_vectors is False


def test_unknown_engine_lists_every_engine():
    """오류 메시지가 엔진 목록과 어긋나면 안 된다.

    문자열을 박아두면 엔진이 늘 때마다 이 테스트가 거짓말을 하거나 깨진다.
    `ENGINES`에서 만들어 대조한다 — 실제로 `rules+`·`vector+`를 더할 때
    이 테스트가 깨져서 메시지 갱신을 잊지 않았다.
    """
    from searchclinic.doctor import ENGINES

    with pytest.raises(ValueError, match=", ".join(ENGINES).replace("+", r"\+")):
        make_doctor("없는엔진")


def test_vector_doctor_heals_a_query_the_jamo_doctor_cannot():
    """같은 상태 기계, 같은 게이트 — 자 하나 차이로 결과가 갈리는지."""
    query = "블루투스 스피커"
    base = run_doctor_session(_executor(), make_doctor("scripted"), query)
    assert not base.healed  # 전제: 자모만으로는 못 푼다

    vec = run_doctor_session(_executor(CachedVectors(FAKE)), make_doctor("vector"), query)
    assert vec.healed
    assert vec.diagnosis_family == "cross_script"


# --------------------------------------------------------------- 설치 오류 안내

def _backend_without_torch(monkeypatch, exc):
    """torch import만 실패하도록 만든 뒤 백엔드를 만들어 본다."""
    import builtins

    from searchclinic.analysis.vectors import SentenceTransformerBackend

    real_import = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "torch":
            raise exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)
    return SentenceTransformerBackend


def test_missing_torch_gives_actionable_message(monkeypatch):
    """torch가 없을 때 라이브러리 안쪽의 날것 오류가 새어나오면 안 된다.

    실측 실패: sentence-transformers만 깔린 환경에서
    `NameError: name 'torch' is not defined`가 그대로 튀어나왔다.
    그 메시지로는 무엇을 해야 할지 알 수 없다.
    """
    Backend = _backend_without_torch(monkeypatch, NameError("name 'torch' is not defined"))
    with pytest.raises(RuntimeError, match="PyTorch를 불러올 수 없습니다"):
        Backend()


def test_intel_mac_hint_is_included(monkeypatch):
    """인텔 맥은 torch 2.2.2가 마지막이라 그 안내가 메시지에 있어야 한다."""
    Backend = _backend_without_torch(monkeypatch, ImportError("No module named 'torch'"))
    with pytest.raises(RuntimeError, match=r"torch<=2\.2\.2"):
        Backend()
