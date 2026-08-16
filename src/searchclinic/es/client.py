"""최소 Elasticsearch HTTP 클라이언트 (표준 라이브러리만).

`elasticsearch-py`를 쓰지 않는 이유는 셋이다:

1. 이 프로젝트가 ES에 요구하는 것은 인덱스 생성·bulk 색인·search·analyze
   네 가지뿐이다. 의존성 하나를 더 얹을 만한 표면적이 아니다.
2. 클라이언트 버전과 서버 버전이 어긋나면 라이브러리가 요청 자체를 거부한다.
   검증 도구가 버전 협상 때문에 실패하는 것은 노이즈다.
3. 실제로 오가는 JSON이 그대로 보여야 한다. 이 모듈의 목적은 "로컬 패치가
   nori 설정으로 정확히 옮겨졌는가"의 검증이고, 그러려면 요청 본문이
   추상화 뒤에 숨지 않아야 한다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ESError(RuntimeError):
    """ES가 4xx/5xx로 응답했을 때. 본문을 그대로 실어 원인을 보이게 한다."""


class ESClient:
    def __init__(self, url: str = "http://localhost:9200", timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------ 저수준

    def _request(self, method: str, path: str, body: Any = None) -> dict:
        data = None
        headers = {}
        if isinstance(body, str):  # bulk NDJSON
            data = body.encode("utf-8")
            headers["Content-Type"] = "application/x-ndjson"
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            f"{self.url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise ESError(f"{method} {path} → HTTP {e.code}\n{detail}") from e
        except urllib.error.URLError as e:
            raise ESError(
                f"Elasticsearch에 연결할 수 없습니다: {self.url} ({e.reason})\n"
                f"docker/ 아래의 compose로 먼저 띄우세요: "
                f"docker compose -f docker/docker-compose.yml up -d"
            ) from e

    # ------------------------------------------------------------ 고수준

    def ping(self) -> dict:
        return self._request("GET", "/")

    def has_nori(self) -> bool:
        """analysis-nori 플러그인이 설치돼 있는지. 없으면 인덱스 생성이 실패한다."""
        nodes = self._request("GET", "/_nodes/plugins")
        return any(
            p.get("name") == "analysis-nori"
            for node in nodes.get("nodes", {}).values()
            for p in node.get("plugins", [])
        )

    def delete_index(self, index: str) -> None:
        try:
            self._request("DELETE", f"/{index}")
        except ESError as e:
            if "index_not_found_exception" not in str(e):
                raise

    def create_index(self, index: str, settings: dict) -> dict:
        # 렌더러가 붙이는 _meta는 인덱스 설정 스키마에 없는 키라 제거한다.
        body = {k: v for k, v in settings.items() if not k.startswith("_")}
        return self._request("PUT", f"/{index}", body)

    def bulk_index(self, index: str, docs: list[dict], id_field: str = "doc_id") -> dict:
        lines = []
        for d in docs:
            lines.append(json.dumps({"index": {"_id": d[id_field]}}, ensure_ascii=False))
            lines.append(json.dumps(d, ensure_ascii=False))
        result = self._request("POST", f"/{index}/_bulk?refresh=wait_for", "\n".join(lines) + "\n")
        if result.get("errors"):
            first = next(
                (item for item in result.get("items", []) if "error" in item.get("index", {})),
                None,
            )
            raise ESError(f"bulk 색인 실패: {json.dumps(first, ensure_ascii=False)}")
        return result

    def search(self, index: str, query: str, field: str = "text", k: int = 10) -> list[dict]:
        body = {
            "size": k,
            "query": {"match": {field: {"query": query}}},
            "_source": False,
        }
        resp = self._request("POST", f"/{index}/_search", body)
        return [
            {"doc_id": h["_id"], "score": h["_score"]}
            for h in resp.get("hits", {}).get("hits", [])
        ]

    def analyze(self, index: str, text: str, analyzer: str = "clinic_korean") -> list[dict]:
        """nori가 이 텍스트를 어떻게 쪼개는지 — Kiwi와의 차이를 설명하는 근거."""
        resp = self._request(
            "POST", f"/{index}/_analyze", {"analyzer": analyzer, "text": text}
        )
        return [
            {"token": t["token"], "type": t.get("type", ""), "position": t.get("position")}
            for t in resp.get("tokens", [])
        ]
