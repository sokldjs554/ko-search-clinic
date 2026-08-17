"""REST API — HTTP 표현이 도메인 규칙을 배신하지 않는지.

여기서 시험할 것은 라우트가 있는지가 아니라, **프로토콜을 갈아탄 뒤에도
같은 것이 보장되는가**이다. 특히:

    게이트를 우회할 수 없다        (과잉 처방은 여전히 기각된다)
    기각은 4xx가 아니다            (요청이 틀린 게 아니라 처방이 안 된 것)
    정답표는 응답에 없다
    세션 격리가 HTTP 너머에서도 유지된다
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="REST는 선택 의존성이다")
from fastapi.testclient import TestClient  # noqa: E402

from searchclinic.api.rest import create_app  # noqa: E402
from searchclinic.service import ClinicService  # noqa: E402

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
def client():
    return TestClient(create_app(ClinicService()))


def _open_session(client, query="후라이팬"):
    sid = client.post("/sessions", json={"label": "테스트"}).json()["session_id"]
    client.post(f"/sessions/{sid}/target", json={"query": query})
    return sid


# --------------------------------------------------------------- 읽기 전용

def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["failing_queries"] == 16


def test_tools_endpoint_matches_the_doctor_tools(client):
    names = {t["name"] for t in client.get("/tools").json()["tools"]}
    assert "submit_prescription" in names and "analyze_text" in names


def test_evalset_does_not_leak_qrels(client):
    body = client.get("/evalset").json()
    assert body["queries"] and "qrels" not in str(body)


def test_analyze_reports_dropped_tokens(client):
    body = client.post("/analyze", json={"text": "아답터"}).json()
    assert "아" in [d["token"] for d in body["dropped"]]


def test_search_on_baseline_is_unpatched(client):
    assert client.post("/search", json={"query": "후라이팬"}).json()["total"] == 0


def test_evaluate_separates_failing_from_healthy(client):
    """전체 평균 하나만 보면 실패를 고치며 건강을 망가뜨린 것이 상쇄돼 보인다."""
    body = client.get("/evaluate").json()
    assert body["failing_mean_ndcg"] < body["healthy_mean_ndcg"]


# --------------------------------------------------------------- 유효성

@pytest.mark.parametrize(
    "path,payload",
    [("/search", {"query": "", "k": 5}), ("/search", {"query": "가", "k": 0}), ("/analyze", {"text": ""})],
)
def test_invalid_input_is_422_not_500(client, path, payload):
    assert client.post(path, json=payload).status_code == 422


def test_missing_session_is_404(client):
    assert client.get("/sessions/없는세션").status_code == 404
    assert client.delete("/sessions/없는세션").status_code == 404


def test_unknown_tool_is_404(client):
    sid = _open_session(client)
    r = client.post(f"/sessions/{sid}/tools", json={"name": "없는도구", "input": {}})
    assert r.status_code == 404


def test_schema_violation_is_400(client):
    sid = _open_session(client)
    r = client.post(f"/sessions/{sid}/prescriptions", json={**GOOD_RX, "reasoning": "짧음"})
    assert r.status_code == 400


def test_target_mismatch_is_400(client):
    """표적을 바꿔 던진 처방이 통과하면 기록이 통째로 거짓이 된다."""
    sid = _open_session(client)
    r = client.post(f"/sessions/{sid}/prescriptions", json={**GOOD_RX, "target_query": "티슈"})
    assert r.status_code == 400 and "표적" in r.json()["detail"]


def test_query_outside_the_evalset_is_400(client):
    sid = client.post("/sessions", json={}).json()["session_id"]
    r = client.post(f"/sessions/{sid}/target", json={"query": "평가셋에없는질의"})
    assert r.status_code == 400


# ----------------------------------------------------------------- 게이트

def test_good_prescription_is_accepted_with_200(client):
    sid = _open_session(client)
    r = client.post(f"/sessions/{sid}/prescriptions", json=GOOD_RX)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["target_ndcg_before"] == 0.0 and body["target_ndcg_after"] == 1.0


def test_overbroad_prescription_is_rejected_but_not_an_error(client):
    """기각은 오류가 아니다 — 4xx로 답하면 '요청이 틀렸다'는 잘못된 신호가 된다."""
    sid = _open_session(client)
    r = client.post(f"/sessions/{sid}/prescriptions", json=OVERBROAD_RX)

    assert r.status_code == 202
    body = r.json()
    assert body["accepted"] is False
    assert "회귀" in body["feedback"]
    # 기각된 설정이 조금이라도 남으면 이후 진료가 오염된 기준 위에서 돈다.
    assert client.get(f"/sessions/{sid}").json()["accepted_count"] == 0


def test_accepted_patch_shows_up_in_the_ledger_with_evidence(client):
    sid = _open_session(client)
    client.post(f"/sessions/{sid}/prescriptions", json=GOOD_RX)
    entry = client.get(f"/sessions/{sid}").json()["ledger"][0]
    assert entry["summary"] == "동의어(프라이팬 = 후라이팬)"
    assert entry["evidence"]["regressions"] == 0


# ----------------------------------------------------------------- 세션

def test_patch_is_visible_in_its_session_and_nowhere_else(client):
    sid = _open_session(client)
    client.post(f"/sessions/{sid}/prescriptions", json=GOOD_RX)

    assert client.post("/search", json={"query": "후라이팬", "session_id": sid}).json()["total"] > 0
    assert client.post("/search", json={"query": "후라이팬"}).json()["total"] == 0

    other = client.post("/sessions", json={}).json()["session_id"]
    assert client.post("/search", json={"query": "후라이팬", "session_id": other}).json()["total"] == 0


def test_deleted_session_is_gone(client):
    sid = client.post("/sessions", json={}).json()["session_id"]
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert client.get(f"/sessions/{sid}").status_code == 404


def test_evaluate_reflects_the_session_patch(client):
    sid = _open_session(client)
    before = client.get("/evaluate", params={"session_id": sid}).json()["mean_ndcg"]
    client.post(f"/sessions/{sid}/prescriptions", json=GOOD_RX)
    after = client.get("/evaluate", params={"session_id": sid}).json()["mean_ndcg"]
    assert after > before


# --------------------------------------------------------------- ES 렌더링

def test_elasticsearch_endpoint_carries_static_validation(client):
    sid = _open_session(client)
    client.post(f"/sessions/{sid}/prescriptions", json=GOOD_RX)
    body = client.get(f"/sessions/{sid}/elasticsearch").json()

    assert body["problems"] == []
    tokenizer = body["settings"]["settings"]["index"]["analysis"]["tokenizer"]
    assert "후라이팬" in tokenizer["clinic_korean_tokenizer"]["user_dictionary_rules"]


def test_elasticsearch_index_name_is_configurable(client):
    sid = _open_session(client)
    body = client.get(f"/sessions/{sid}/elasticsearch", params={"index_name": "상품"}).json()
    assert body["index_name"] == "상품"


# ------------------------------------------------------------ 도구 통로

def test_tool_endpoint_and_mcp_share_one_path(client):
    """REST의 /tools 호출과 MCP 도구 호출이 같은 실행기를 지난다."""
    sid = _open_session(client)
    body = client.post(
        f"/sessions/{sid}/tools", json={"name": "search_products", "input": {"query": "노트북 파우치"}}
    ).json()
    assert body["total"] > 0


def test_submitting_through_the_generic_tool_endpoint_still_hits_the_gate(client):
    """도구 통로로 우회해도 게이트를 지나야 한다 — 뒷문이 있으면 안 된다."""
    sid = _open_session(client)
    body = client.post(
        f"/sessions/{sid}/tools", json={"name": "submit_prescription", "input": OVERBROAD_RX}
    ).json()
    assert body["accepted"] is False
    assert client.get(f"/sessions/{sid}").json()["accepted_count"] == 0


def test_openapi_schema_is_served(client):
    """자동 생성 문서가 나온다는 것 자체가 스키마가 유효하다는 뜻이다."""
    schema = client.get("/openapi.json").json()
    assert "/sessions/{session_id}/prescriptions" in schema["paths"]
