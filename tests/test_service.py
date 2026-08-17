"""서비스 계층 — fastapi도 mcp도 없이 전부 돈다.

이 계층의 존재 이유가 "REST와 MCP가 같은 로직을 쓰게 하는 것"이므로,
여기서 보장해야 할 것은 기능 목록이 아니라 **불변식**이다:

    프로토콜을 바꿔도 게이트를 우회할 수 없다
    세션마다 설정이 격리된다
    정답표(qrels)는 밖으로 나가지 않는다
"""

import threading

import pytest

from searchclinic.service import (
    ClinicService,
    SessionNotFound,
    ToolFailed,
    UnknownTool,
)

GOOD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "후라이팬은 프라이팬의 비표준 표기다. 최소 범위 동의어로 잇는다.",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬"]}],
}

OVERBROAD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "팬은 프라이팬의 준말이므로 함께 묶는다 (과잉 일반화).",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬", "팬"]}],
}


@pytest.fixture(scope="module")
def service():
    return ClinicService()


def _healed_session(service, rx=GOOD_RX):
    sid = service.create_session()["session_id"]
    service.open_query(sid, rx["target_query"])
    return sid, service.submit_prescription(sid, rx)


# ------------------------------------------------------------- 읽기 전용

def test_health_reports_real_corpus_scale(service):
    h = service.health()
    assert h["status"] == "ok"
    assert h["documents"] > 0 and h["eval_queries"] > 0
    assert h["failing_queries"] == 16


def test_evalset_never_leaks_qrels(service):
    """정답표가 새면 호출자가 정답을 보고 처방을 맞출 수 있다 — 평가가 죽는다."""
    payload = service.evalset()
    assert payload["queries"]
    for q in payload["queries"]:
        assert "qrels" not in q
    assert "qrels" not in repr(payload)


def test_analyze_surfaces_dropped_tokens(service):
    """`아답터`의 '아'가 감탄사로 오인돼 버려지는 것을 보여야 진단이 가능하다."""
    payload = service.analyze("아답터")
    assert [t["token"] for t in payload["tokens"]] == ["답", "터"]
    assert "아" in [d["token"] for d in payload["dropped"]]


def test_baseline_search_is_unpatched(service):
    """세션 없이 부른 검색은 언제나 치유 전 상태다 — 비교 기준점이 필요하다."""
    assert service.search("후라이팬")["total"] == 0


# ----------------------------------------------------------------- 세션

def test_session_patch_does_not_touch_the_baseline(service):
    sid, result = _healed_session(service)
    assert result["accepted"] is True
    assert service.search("후라이팬", session_id=sid)["total"] > 0
    assert service.search("후라이팬")["total"] == 0  # 기준은 그대로


def test_sessions_are_isolated_from_each_other(service):
    """한 호출자의 패치가 다른 호출자의 색인에 새면 게이트의 보증이 거짓이 된다."""
    sid_a, _ = _healed_session(service)
    sid_b = service.create_session()["session_id"]
    assert service.search("후라이팬", session_id=sid_a)["total"] > 0
    assert service.search("후라이팬", session_id=sid_b)["total"] == 0


def test_missing_session_raises_not_found(service):
    with pytest.raises(SessionNotFound):
        service.describe_session("없는세션")
    with pytest.raises(SessionNotFound):
        service.delete_session("없는세션")


def test_deleted_session_is_gone(service):
    sid = service.create_session()["session_id"]
    service.delete_session(sid)
    with pytest.raises(SessionNotFound):
        service.describe_session(sid)


def test_oldest_session_is_evicted_at_the_cap():
    """세션이 무한정 쌓이면 색인 한 벌씩 물고 메모리를 먹는다."""
    svc = ClinicService(max_sessions=2)
    a = svc.create_session()["session_id"]
    svc.create_session()
    svc.create_session()
    assert svc.list_sessions()["total"] == 2
    with pytest.raises(SessionNotFound):
        svc.describe_session(a)


# ----------------------------------------------------------------- 게이트

def test_gate_still_rejects_overbroad_synonyms_through_the_service(service):
    """프로토콜을 바꿔도 검증을 우회할 수 없다 — 이 설계의 요점."""
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")
    result = service.submit_prescription(sid, OVERBROAD_RX)

    assert result["accepted"] is False
    assert "회귀" in result["feedback"]
    assert service.describe_session(sid)["accepted_count"] == 0


def test_rejected_prescription_leaves_the_session_unchanged(service):
    """기각된 설정이 조금이라도 남으면 이후 진료가 오염된 기준 위에서 돈다."""
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")
    service.submit_prescription(sid, OVERBROAD_RX)
    assert service.describe_session(sid)["config"]["synonym_groups"] == []
    assert service.search("후라이팬", session_id=sid)["total"] == 0


def test_ledger_carries_the_evidence_not_just_the_patch(service):
    """게이트는 '말이 되는가'를 안 본다. 사람이 다시 읽을 근거가 남아야 한다."""
    sid, _ = _healed_session(service)
    entry = service.describe_session(sid)["ledger"][0]
    assert entry["reasoning"]
    assert entry["evidence"]["target_ndcg_before"] < entry["evidence"]["target_ndcg_after"]
    assert entry["evidence"]["regressions"] == 0


def test_target_query_is_pinned_to_the_open_query(service):
    """표적을 바꿔 던진 처방이 채택되면 기록이 통째로 거짓이 된다 (실측 실패)."""
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")
    with pytest.raises(ToolFailed, match="표적"):
        service.submit_prescription(sid, {**GOOD_RX, "target_query": "티슈"})


def test_opening_a_query_outside_the_evalset_is_refused(service):
    """채점할 정답이 없는 질의를 진료하면 게이트가 매번 거부하며 헛돈다."""
    sid = service.create_session()["session_id"]
    with pytest.raises(ToolFailed, match="평가셋에 없는"):
        service.open_query(sid, "평가셋에없는질의")


def test_schema_violation_is_a_tool_failure_not_a_crash(service):
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")
    with pytest.raises(ToolFailed):
        service.submit_prescription(sid, {**GOOD_RX, "reasoning": "짧음"})


# ----------------------------------------------------------------- 도구

def test_tool_definitions_match_the_doctor_tools(service):
    """MCP가 노출할 목록이 의사가 쓰는 목록과 달라지면 두 벌이 된다."""
    names = {t["name"] for t in service.tool_definitions()}
    assert "submit_prescription" in names
    assert {"search_products", "analyze_text", "grep_documents"} <= names
    for t in service.tool_definitions():
        assert t["input_schema"]["type"] == "object"


def test_unknown_tool_is_rejected_before_dispatch(service):
    sid = service.create_session()["session_id"]
    with pytest.raises(UnknownTool):
        service.call_tool(sid, "존재하지_않는_도구", {})


def test_call_tool_returns_parsed_json(service):
    sid = service.create_session()["session_id"]
    payload = service.call_tool(sid, "search_products", {"query": "노트북 파우치"})
    assert isinstance(payload, dict) and payload["total"] > 0


# ------------------------------------------------------------ ES 렌더링

def test_elasticsearch_settings_include_static_validation(service):
    """보내고 500을 받는 것보다 보내기 전에 아는 편이 낫다."""
    sid, _ = _healed_session(service)
    payload = service.elasticsearch_settings(sid)
    assert payload["problems"] == []
    analysis = payload["settings"]["settings"]["index"]["analysis"]
    assert "후라이팬" in analysis["tokenizer"]["clinic_korean_tokenizer"]["user_dictionary_rules"]


# ------------------------------------------------------------ 동시성

def _run_concurrently(fn, n: int = 4) -> tuple[list, list[Exception]]:
    results: list = []
    errors: list[Exception] = []

    def run():
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001 - 무엇이든 기록해서 드러낸다
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_concurrent_duplicate_submissions_accept_exactly_one(service):
    """FastAPI는 동기 핸들러를 **스레드풀**에서 돌린다 — 같은 세션에 겹쳐 들어온다.

    같은 처방이 네 번 겹쳐도 동의어가 네 벌 쌓이면 안 된다. 락이 직렬화하고
    설정 계층의 중복 방지가 나머지를 거절해, 하나만 남고 셋은 **깨끗한 도메인
    오류**가 된다. 경합으로 인한 날것의 예외(AttributeError 등)가 아니라는
    것까지 확인해야 잠금이 실제로 동작한 것이다.
    """
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")

    results, errors = _run_concurrently(lambda: service.submit_prescription(sid, GOOD_RX))

    assert len(results) == 1 and results[0]["accepted"] is True
    assert len(errors) == 3
    assert all(isinstance(e, ToolFailed) and "이미 다른 동의어 그룹" in str(e) for e in errors)
    assert len(service.describe_session(sid)["config"]["synonym_groups"]) == 1


def test_concurrent_reads_during_a_patch_never_see_a_half_applied_config(service):
    """읽기는 패치 전이나 후를 보아야 하고, 그 중간은 없어야 한다."""
    sid = service.create_session()["session_id"]
    service.open_query(sid, "후라이팬")
    patched = [0]

    def read_or_patch():
        if patched[0] == 0:
            patched[0] = 1
            service.submit_prescription(sid, GOOD_RX)
            return None  # bool을 돌려주면 아래 int 필터에 걸린다 (bool은 int다)
        return service.search("후라이팬", session_id=sid)["total"]

    results, errors = _run_concurrently(read_or_patch, n=8)

    assert not errors
    counts = {r for r in results if r is not None}
    assert counts <= {0, 2}  # 패치 전 0건, 패치 후 2건 — 그 사이는 없다
