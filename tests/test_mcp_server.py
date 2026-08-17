"""MCP 서버 — 프로토콜을 갈아타도 규칙이 유지되는가.

`dispatch()`를 순수 함수로 뽑아둔 덕에 대부분은 MCP 세션 없이 시험한다.
전송 계층까지 실제로 무는 것은 마지막 두 개다.
"""

import json

import pytest

pytest.importorskip("mcp", reason="MCP는 선택 의존성이다")

from searchclinic.api.mcp_server import (  # noqa: E402
    LIST_FAILING_TOOL,
    OPEN_TARGET_TOOL,
    build_mcp_tools,
    create_server,
    dispatch,
)
from searchclinic.service import ClinicService, ToolFailed, UnknownTool  # noqa: E402

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


@pytest.fixture
def clinic():
    svc = ClinicService()
    sid = svc.create_session(label="mcp-test")["session_id"]
    return svc, sid


# ------------------------------------------------------------- 도구 목록

def test_doctor_tool_schemas_are_passed_through_untouched():
    """스키마를 다시 선언하면 정의가 두 벌이 되고, 두 벌은 반드시 갈라진다."""
    svc = ClinicService()
    original = {t["name"]: t for t in svc.tool_definitions()}
    exposed = {t["name"]: t for t in build_mcp_tools(svc)}

    for name, tool in original.items():
        assert exposed[name]["input_schema"] == tool["input_schema"]
        assert exposed[name]["description"] == tool["description"]


def test_clinic_tools_are_added_on_top():
    names = {t["name"] for t in build_mcp_tools(ClinicService())}
    assert OPEN_TARGET_TOOL["name"] in names
    assert LIST_FAILING_TOOL["name"] in names
    assert "submit_prescription" in names


def test_every_exposed_tool_has_an_object_schema():
    """스키마가 깨지면 호스트가 도구 목록 자체를 못 읽는다."""
    for t in build_mcp_tools(ClinicService()):
        assert t["input_schema"]["type"] == "object"
        assert t["description"].strip()


# --------------------------------------------------------------- 디스패치

def test_list_failing_queries_hides_the_answer_key(clinic):
    svc, sid = clinic
    payload = dispatch(svc, sid, LIST_FAILING_TOOL["name"], {})
    assert len(payload["failing_queries"]) == 16
    assert "qrels" not in json.dumps(payload, ensure_ascii=False)


def test_open_target_pins_the_query(clinic):
    svc, sid = clinic
    assert dispatch(svc, sid, OPEN_TARGET_TOOL["name"], {"query": "후라이팬"})["target_query"] == "후라이팬"
    with pytest.raises(ToolFailed, match="표적"):
        dispatch(svc, sid, "submit_prescription", {**GOOD_RX, "target_query": "티슈"})


def test_open_target_refuses_queries_outside_the_evalset(clinic):
    svc, sid = clinic
    with pytest.raises(ToolFailed, match="평가셋에 없는"):
        dispatch(svc, sid, OPEN_TARGET_TOOL["name"], {"query": "평가셋에없는질의"})


def test_unknown_tool_raises(clinic):
    svc, sid = clinic
    with pytest.raises(UnknownTool):
        dispatch(svc, sid, "없는도구", {})


def test_gate_is_not_bypassed_over_mcp(clinic):
    """외부 모델이 아무리 확신해도 회귀를 만드는 처방은 채택되지 않는다."""
    svc, sid = clinic
    dispatch(svc, sid, OPEN_TARGET_TOOL["name"], {"query": "후라이팬"})
    result = dispatch(svc, sid, "submit_prescription", OVERBROAD_RX)

    assert result["accepted"] is False
    assert "회귀" in result["feedback"]
    assert svc.describe_session(sid)["accepted_count"] == 0


def test_good_prescription_is_accepted_over_mcp(clinic):
    svc, sid = clinic
    dispatch(svc, sid, OPEN_TARGET_TOOL["name"], {"query": "후라이팬"})
    result = dispatch(svc, sid, "submit_prescription", GOOD_RX)

    assert result["accepted"] is True
    assert svc.search("후라이팬", session_id=sid)["total"] > 0
    assert svc.search("후라이팬")["total"] == 0  # 기준 색인은 그대로


def test_evidence_tools_work_over_mcp(clinic):
    svc, sid = clinic
    analyzed = dispatch(svc, sid, "analyze_text", {"text": "아답터"})
    assert [t["token"] for t in analyzed["tokens"]] == ["답", "터"]

    grepped = dispatch(svc, sid, "grep_documents", {"text": "어댑터"})
    assert grepped["total"] > 0  # 검색은 0건인데 grep엔 있다 — 진단의 결정적 증거


# ------------------------------------------------------------- 전송 계층

@pytest.mark.anyio
async def test_server_lists_tools_over_the_protocol():
    """실제 핸들러가 프로토콜 타입으로 목록을 낸다."""
    server = create_server(ClinicService())
    handler = server.get_request_handler("tools/list")
    result = await handler.handler(None, None)

    names = {t.name for t in result.tools}
    assert "submit_prescription" in names and OPEN_TARGET_TOOL["name"] in names


@pytest.mark.anyio
async def test_tool_errors_come_back_as_is_error_not_a_crash():
    """도구 오류가 전송 계층을 죽이면 호스트는 서버가 죽은 줄 안다."""
    from mcp.types import CallToolRequestParams

    server = create_server(ClinicService())
    handler = server.get_request_handler("tools/call")

    result = await handler.handler(None, CallToolRequestParams(name="없는도구", arguments={}))
    assert result.is_error is True
    assert "없는 도구" in result.content[0].text


@pytest.mark.anyio
async def test_rejected_prescription_is_not_an_error_over_the_protocol():
    """기각은 판정이지 오류가 아니다 — 모델은 사유를 읽고 처방을 좁혀야 한다."""
    from mcp.types import CallToolRequestParams

    server = create_server(ClinicService())
    handler = server.get_request_handler("tools/call")

    await handler.handler(
        None, CallToolRequestParams(name=OPEN_TARGET_TOOL["name"], arguments={"query": "후라이팬"})
    )
    result = await handler.handler(
        None, CallToolRequestParams(name="submit_prescription", arguments=OVERBROAD_RX)
    )

    assert result.is_error is False
    body = json.loads(result.content[0].text)
    assert body["accepted"] is False and "회귀" in body["feedback"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
