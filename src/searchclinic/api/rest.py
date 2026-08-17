"""REST API — 진료소를 HTTP로 연다.

라우트에 로직을 두지 않는다. 전부 `ClinicService` 호출 한 줄이고, 이 파일이
하는 일은 **HTTP 표현으로 옮기는 것**뿐이다. 그래야 REST와 MCP가 같은 것을
답한다.

## 무엇을 어떤 상태 코드로 옮기는가

서비스 계층은 HTTP를 모른 채 도메인 예외를 던진다. 그 대응을 한 곳에 모은다:

    SessionNotFound → 404   없는 세션
    UnknownTool     → 404   정의되지 않은 도구
    ToolFailed      → 400   호출자가 고칠 수 있는 문제 (스키마 위반, 표적 불일치)

**기각된 처방은 오류가 아니다.** 게이트가 거절한 것은 요청이 잘못돼서가
아니라 그 처방이 회귀를 만들기 때문이고, 호출자는 그 사유를 읽고 처방을
좁혀 다시 던져야 한다. 그래서 `202`로 답하고 `accepted: false`와 회귀 목록을
본문에 담는다 — 4xx로 답하면 "요청이 틀렸다"는 잘못된 신호가 된다.

## 왜 세션이 URL에 드러나는가

진료는 상태를 쌓는 절차다(채택된 처방이 다음 진료의 기준이 된다). 그 상태를
서버가 암묵적으로 들고 있으면 호출자는 자기가 무엇 위에서 일하는지 모른다.
`/sessions/{id}` 아래로 내려서 **누구의 설정 위인지를 URL이 말하게** 한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from searchclinic.service import (
    ClinicService,
    SessionNotFound,
    ToolFailed,
    UnknownTool,
)

# 게이트 기각을 나타내는 상태 코드. 요청은 옳았고 처방이 채택되지 않았을 뿐이다.
GATE_REJECTED = 202


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    session_id: str | None = None


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str | None = None


class SessionRequest(BaseModel):
    label: str = ""


class OpenQueryRequest(BaseModel):
    query: str = Field(min_length=1)


class ToolCallRequest(BaseModel):
    name: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


def create_app(service: ClinicService | None = None) -> FastAPI:
    """앱을 만든다. 서비스를 주입받는 이유는 테스트가 자기 것을 쓰기 위해서다."""
    svc = service or ClinicService()
    app = FastAPI(
        title="ko-search-clinic",
        description=(
            "한국어 검색 품질 자가 치유 진료소. 처방은 평가셋 전수 재실행 "
            "게이트를 통과해야만 채택된다 — 이 API로도 우회할 수 없다."
        ),
        version="0.1.0",
    )

    # 도메인 예외를 HTTP로 옮기는 유일한 자리. 라우트마다 try/except를 두면
    # 하나를 빠뜨렸을 때 500이 나가고, 그 500은 호출자에게 아무것도 알려주지 않는다.
    @app.exception_handler(SessionNotFound)
    def _session_not_found(_request, exc: SessionNotFound):
        return JSONResponse(status_code=404, content={"detail": f"없는 세션: {exc.args[0]}"})

    @app.exception_handler(UnknownTool)
    def _unknown_tool(_request, exc: UnknownTool):
        return JSONResponse(status_code=404, content={"detail": f"없는 도구: {exc.args[0]}"})

    @app.exception_handler(ToolFailed)
    def _tool_failed(_request, exc: ToolFailed):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ------------------------------------------------------------ 읽기 전용

    @app.get("/health", tags=["진료소"])
    def health() -> dict:
        return svc.health()

    @app.get("/tools", tags=["진료소"])
    def tools() -> dict:
        """진료 도구 스키마. MCP가 노출하는 것과 **같은 목록**이다."""
        return {"tools": svc.tool_definitions()}

    @app.get("/evalset", tags=["평가"])
    def evalset() -> dict:
        """평가셋. 정답표(qrels)는 포함되지 않는다 — 채점자만 본다."""
        return svc.evalset()

    @app.get("/evaluate", tags=["평가"])
    def evaluate(session_id: str | None = Query(default=None)) -> dict:
        """평가셋 전체 채점. session_id를 주면 그 세션의 누적 패치 위에서 잰다."""
        return svc.evaluate(session_id)

    @app.post("/search", tags=["검색"])
    def search(req: SearchRequest) -> dict:
        return svc.search(req.query, k=req.k, session_id=req.session_id)

    @app.post("/analyze", tags=["검색"])
    def analyze(req: AnalyzeRequest) -> dict:
        """형태소 분석 결과 + 내용어 필터에서 **버려진** 토큰."""
        return svc.analyze(req.text, session_id=req.session_id)

    # ---------------------------------------------------------------- 세션

    @app.post("/sessions", status_code=201, tags=["세션"])
    def create_session(req: SessionRequest | None = None) -> dict:
        return svc.create_session(label=(req.label if req else ""))

    @app.get("/sessions", tags=["세션"])
    def list_sessions() -> dict:
        return svc.list_sessions()

    @app.get("/sessions/{session_id}", tags=["세션"])
    def describe_session(session_id: str) -> dict:
        return svc.describe_session(session_id)

    @app.delete("/sessions/{session_id}", tags=["세션"])
    def delete_session(session_id: str) -> dict:
        return svc.delete_session(session_id)

    @app.post("/sessions/{session_id}/target", tags=["세션"])
    def open_query(session_id: str, req: OpenQueryRequest) -> dict:
        """진료 표적을 못박는다. 이후 제출은 이 질의만 표적으로 삼을 수 있다."""
        return svc.open_query(session_id, req.query)

    @app.post("/sessions/{session_id}/tools", tags=["세션"])
    def call_tool(session_id: str, req: ToolCallRequest) -> dict:
        """도구 하나를 실행한다 — MCP 도구 호출과 **같은 통로**를 쓴다."""
        return svc.call_tool(session_id, req.name, req.input)

    @app.post("/sessions/{session_id}/prescriptions", tags=["세션"])
    def submit_prescription(session_id: str, prescription: dict[str, Any]) -> JSONResponse:
        """처방 제출 → 게이트 판정.

        채택이면 200, 기각이면 202다. 기각은 오류가 아니라 **판정 결과**이며,
        본문의 feedback에 어떤 질의가 어떻게 나빠졌는지가 들어 있다.
        """
        result = svc.submit_prescription(session_id, prescription)
        return JSONResponse(
            status_code=200 if result["accepted"] else GATE_REJECTED, content=result
        )

    @app.get("/sessions/{session_id}/elasticsearch", tags=["세션"])
    def elasticsearch_settings(
        session_id: str, index_name: str = Query(default="products")
    ) -> dict:
        """세션의 누적 설정을 ES nori 인덱스 설정으로 렌더링한다.

        `problems`가 비어 있지 않으면 ES가 인덱스 생성을 거부한다 — 보내기
        전에 알 수 있도록 정적 검증 결과를 함께 싣는다.
        """
        return svc.elasticsearch_settings(session_id, index_name=index_name)

    return app


def main(argv: list[str] | None = None) -> int:
    """`clinic-api` 진입점. uvicorn으로 앱을 띄운다."""
    import argparse

    parser = argparse.ArgumentParser(prog="clinic-api", description="ko-search-clinic REST API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print('uvicorn이 필요합니다:  pip install -e ".[api]"')
        return 1

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
