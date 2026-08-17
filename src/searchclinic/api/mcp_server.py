"""MCP 서버 — 진료소를 외부 LLM 호스트의 도구로 연다.

Claude Desktop 같은 MCP 호스트가 이 서버를 물면, 그 호스트의 모델이 곧
**의사**가 된다. 이 저장소의 `--engine claude`가 하던 일을 프로세스 밖의
모델이 하는 것이고, 도구·게이트·평가셋은 그대로다.

## 스키마를 다시 쓰지 않는다

진료 도구 6종은 이미 `build_tool_definitions()`에 JSON 스키마로 정의돼 있고,
지금까지의 모든 실측이 **그 설명문 위에서** 나왔다. 도구를 파이썬 함수로 다시
선언해 스키마를 유도하면 정의가 두 벌이 되고, 두 벌은 반드시 갈라진다.
그래서 고수준 데코레이터(`MCPServer.tool`) 대신 저수준 `Server`를 써서
**있는 스키마를 그대로 넘긴다.**

## 게이트는 여기서도 우회되지 않는다

`submit_prescription`은 MCP를 통해 들어와도 평가셋 전수 재실행을 거친다.
외부 모델이 아무리 확신에 차 있어도 회귀를 만드는 처방은 채택되지 않는다 —
**검증이 프로토콜이 아니라 도구 안에 있기 때문**이다. 이것이 이 서버를
만들며 확인하고 싶었던 성질이다.

## 세션 하나를 쓴다

MCP 호스트는 대개 서버 하나를 한 대화에 붙인다. 그래서 프로세스마다 진료
세션 하나를 열고 그 위에서 패치를 누적한다. 세션 관리를 도구로 노출하면
모델이 자기가 어느 설정 위에 있는지를 매 턴 신경 써야 하는데, 그것은 진단과
무관한 부담이다.

실행:
    clinic-mcp                      # stdio (MCP 호스트가 이 방식으로 띄운다)
"""

from __future__ import annotations

import json

from searchclinic.service import ClinicService, ToolFailed, UnknownTool

SERVER_NAME = "ko-search-clinic"
SERVER_VERSION = "0.1.0"

INSTRUCTIONS = """한국어 검색 품질 진료소다.

실패한 한국어 검색 질의를 진단하고, 분석기 설정 패치(사용자 사전 / 동의어 /
복합어 분해)를 처방한다. 제출한 처방은 평가셋 36질의 전수 재실행 게이트를
거치며, 표적이 개선되고 다른 질의에 회귀가 없어야만 채택된다.

절차: open_target으로 표적을 정하고 → search_products·grep_documents·
analyze_text로 증거를 모으고 → submit_prescription으로 제출한다.
기각되면 회귀 목록이 돌아오니 처방을 좁혀 다시 제출하라.

처방은 최소여야 한다. 넓은 동의어 묶음은 거의 확실히 회귀를 만든다."""

# 진료 표적을 여는 도구. 나머지 6종은 의사 도구를 그대로 노출하므로 여기에만
# 따로 정의한다 — 표적을 못박지 않으면 다른 질의를 표적으로 던진 처방이
# 채택되고, 기록에는 원래 질의를 치유한 것으로 남는다 (실측으로 겪은 실패다).
OPEN_TARGET_TOOL = {
    "name": "open_target",
    "description": (
        "진료할 실패 질의를 정한다. 가장 먼저 호출하라. 이후 "
        "submit_prescription은 이 질의만 표적으로 삼을 수 있다. "
        "평가셋에 없는 질의는 채점할 정답이 없으므로 거부된다."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "진료할 질의"}},
        "required": ["query"],
    },
}

LIST_FAILING_TOOL = {
    "name": "list_failing_queries",
    "description": (
        "진료 대상인 실패 질의 목록과 각 질의의 실패 계열을 보여준다. "
        "무엇을 고칠 수 있는지 모를 때 호출하라. 정답 문서 목록(qrels)은 "
        "제공되지 않는다 — 채점은 게이트만 한다."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def build_mcp_tools(service: ClinicService) -> list[dict]:
    """MCP가 노출할 도구 목록 = 진료 도구 6종 + 진료소 도구 2종.

    앞의 6종은 `build_tool_definitions()`가 준 것을 **손대지 않고** 쓴다.
    """
    return [*service.tool_definitions(), OPEN_TARGET_TOOL, LIST_FAILING_TOOL]


def dispatch(service: ClinicService, session_id: str, name: str, arguments: dict) -> dict:
    """도구 하나를 실행한다 — MCP 전송 계층과 무관한 순수 함수.

    여기를 순수하게 두는 이유는 테스트가 MCP 세션을 띄우지 않고도 규칙을
    시험할 수 있어야 하기 때문이다.
    """
    if name == OPEN_TARGET_TOOL["name"]:
        return service.open_query(session_id, arguments["query"])
    if name == LIST_FAILING_TOOL["name"]:
        return {
            "failing_queries": [
                {"query": q["query"], "family": q["family"]}
                for q in service.evalset()["queries"]
                if not q["is_healthy"]
            ]
        }
    return service.call_tool(session_id, name, arguments)


def create_server(service: ClinicService | None = None):
    """저수준 MCP 서버를 만든다. 서비스를 주입받는 이유는 테스트 때문이다."""
    from mcp.server.lowlevel.server import Server
    from mcp.types import (
        CallToolResult,
        ListToolsResult,
        TextContent,
        Tool,
    )

    svc = service or ClinicService()
    session_id = svc.create_session(label="mcp")["session_id"]

    async def on_list_tools(_ctx, _params) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name=t["name"],
                    description=t["description"],
                    input_schema=t["input_schema"],
                )
                for t in build_mcp_tools(svc)
            ]
        )

    async def on_call_tool(_ctx, params) -> CallToolResult:
        def text(payload: object, is_error: bool = False) -> CallToolResult:
            body = payload if isinstance(payload, str) else json.dumps(
                payload, ensure_ascii=False, default=str
            )
            return CallToolResult(
                content=[TextContent(type="text", text=body)], is_error=is_error
            )

        try:
            return text(dispatch(svc, session_id, params.name, params.arguments or {}))
        except UnknownTool as e:
            return text(f"없는 도구: {e.args[0]}", is_error=True)
        except ToolFailed as e:
            # 호출자가 고칠 수 있는 문제다. 오류로 표시하되 사유를 그대로 넘겨
            # 모델이 처방을 좁혀 다시 던질 수 있게 한다.
            return text(str(e), is_error=True)
        except Exception as e:  # noqa: BLE001 - 전송 계층을 죽이지 않는다
            return text(f"도구 실행 실패: {type(e).__name__}: {e}", is_error=True)

    return Server(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def main(argv: list[str] | None = None) -> int:
    """`clinic-mcp` 진입점 — stdio로 돈다."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(prog="clinic-mcp", description="ko-search-clinic MCP 서버")
    parser.parse_args(argv)

    try:
        from mcp.server.stdio import stdio_server
    except ImportError:
        print('mcp가 필요합니다:  pip install -e ".[mcp]"')
        return 1

    server = create_server()

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
