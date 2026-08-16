"""ES 검증 계층 테스트 — Docker 없이 전부 돈다.

실제 Elasticsearch를 띄우는 것은 `clinic es-verify`의 몫이고, 여기서는
그 위아래를 고정한다: 클라이언트가 만드는 요청의 형태, 그리고 결과를
받았을 때 대조 리포트가 무엇을 말하는지.

ES가 있어야만 검증되는 코드는 CI에서 영영 안 돌게 되고, 안 도는 코드는
반드시 썩는다.
"""

import base64
import json

import pytest

from searchclinic.analysis.config import AnalyzerConfig, SynonymGroup
from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.es.client import ESClient, ESError
from searchclinic.es.engine import ElasticsearchEngine
from searchclinic.es.verify import (
    DIVERGENCE_EPS,
    render_verification_markdown,
    verify,
)
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.es_render import to_es_settings


class FakeClient(ESClient):
    """HTTP를 타지 않고 오간 요청을 기록하는 클라이언트."""

    def __init__(self, hits=None, tokens=None):
        super().__init__("http://fake:9200")
        self.calls: list[tuple] = []
        self._hits = hits or {}
        self._tokens = tokens or {}

    def _request(self, method, path, body=None):  # pragma: no cover - 안전망
        raise AssertionError(f"실제 요청이 나갔다: {method} {path}")

    def delete_index(self, index):
        self.calls.append(("delete", index))

    def create_index(self, index, settings):
        self.calls.append(("create", index, settings))
        return {"acknowledged": True}

    def bulk_index(self, index, docs, id_field="doc_id"):
        self.calls.append(("bulk", index, docs))
        return {"errors": False}

    def search(self, index, query, field="text", k=10):
        self.calls.append(("search", index, query, field, k))
        return self._hits.get(query, [])

    def analyze(self, index, text, analyzer="clinic_korean"):
        return [{"token": t} for t in self._tokens.get(text, text.split())]


# --------------------------------------------------------------- 렌더러 계약


def test_rendered_mapping_has_combined_text_field():
    """로컬은 name+description을 통짜로 색인한다 — ES도 같은 텍스트를 재야 한다.

    필드를 나눠 검색하면 BM25의 필드 길이 정규화가 달라져 점수 비교가
    성립하지 않는다. copy_to로 합친 text 필드가 그 대응물이다.
    """
    props = to_es_settings(AnalyzerConfig())["mappings"]["properties"]
    assert props["text"]["analyzer"] == "clinic_korean"
    assert props["name"]["copy_to"] == "text"
    assert props["description"]["copy_to"] == "text"


def test_create_index_strips_meta_key():
    """_meta는 렌더러가 사람 보라고 붙인 것이지 ES 인덱스 설정이 아니다."""
    sent = {}

    class C(ESClient):
        def _request(self, method, path, body=None):
            sent.update({"method": method, "path": path, "body": body})
            return {}

    settings = to_es_settings(AnalyzerConfig())
    assert "_meta" in settings  # 렌더러는 붙인다
    C("http://x").create_index("idx", settings)
    assert "_meta" not in sent["body"]
    assert "settings" in sent["body"] and "mappings" in sent["body"]


# --------------------------------------------------------------- 클라이언트


def test_bulk_body_is_ndjson_with_doc_ids():
    """bulk는 액션 줄과 문서 줄이 번갈아 오는 NDJSON이고, _id는 doc_id다."""
    sent = {}

    class C(ESClient):
        def _request(self, method, path, body=None):
            sent.update({"path": path, "body": body})
            return {"errors": False}

    C("http://x").bulk_index("idx", [{"doc_id": "P001", "name": "프라이팬"}])
    lines = [line for line in sent["body"].split("\n") if line]
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"index": {"_id": "P001"}}
    assert json.loads(lines[1])["doc_id"] == "P001"
    assert "refresh" in sent["path"]  # 색인 직후 검색해야 하므로 refresh 필수


def test_bulk_raises_on_indexing_error():
    """bulk는 HTTP 200이면서 본문에 실패를 담는다 — 조용히 넘어가면 안 된다."""

    class C(ESClient):
        def _request(self, method, path, body=None):
            return {
                "errors": True,
                "items": [{"index": {"_id": "P001", "error": {"type": "mapper_parsing"}}}],
            }

    with pytest.raises(ESError, match="bulk 색인 실패"):
        C("http://x").bulk_index("idx", [{"doc_id": "P001"}])


def test_has_nori_reads_plugin_list():
    class C(ESClient):
        def __init__(self, plugins):
            super().__init__("http://x")
            self._plugins = plugins

        def _request(self, method, path, body=None):
            return {"nodes": {"n1": {"plugins": self._plugins}}}

    assert C([{"name": "analysis-nori"}]).has_nori()
    assert not C([{"name": "analysis-icu"}]).has_nori()


# --------------------------------------------------------------- ES 엔진


def test_engine_reindex_creates_then_bulks():
    docs = load_catalog()
    client = FakeClient()
    ElasticsearchEngine(client, docs, AnalyzerConfig(), index="t").reindex()
    kinds = [c[0] for c in client.calls]
    assert kinds == ["delete", "create", "bulk"]
    assert len(client.calls[2][2]) == len(docs)


def test_engine_search_returns_local_shaped_hits():
    """채점 코드가 로컬 엔진과 ES 엔진을 구분하지 못해야 한다."""
    client = FakeClient(hits={"백팩": [{"doc_id": "P110", "score": 3.2}]})
    es = ElasticsearchEngine(client, load_catalog(), AnalyzerConfig(), index="t")
    hits = es.search("백팩", k=10)
    assert [h.doc_id for h in hits] == ["P110"]
    assert hits[0].score == 3.2


# --------------------------------------------------------------- 대조 리포트


def _local_engine():
    # 후라이팬만 고쳐 둔 설정 — 로컬에서 이 질의는 성공한다
    cfg = AnalyzerConfig(
        synonym_groups=[SynonymGroup(terms=["프라이팬", "후라이팬"])]
    )
    return SearchEngine(load_catalog(), cfg)


def test_divergence_is_flagged_when_es_fails_a_query_local_solved():
    """로컬은 고쳤는데 ES가 못 고치면 반드시 드러나야 한다 — 검증의 존재 이유."""
    local = _local_engine()
    queries = [q for q in load_evalset() if q.query == "후라이팬"]
    assert local.search("후라이팬"), "전제: 로컬은 이 질의를 푼다"

    es = ElasticsearchEngine(FakeClient(hits={}), load_catalog(), local.config, index="t")
    report = verify(local, es, queries)

    (row,) = report.rows
    assert row.local.ndcg > 0 and row.es.ndcg == 0.0
    assert row.diverged and row.ndcg_delta < -DIVERGENCE_EPS
    assert "⚠️" in render_verification_markdown(report)
    assert "갈린 질의" in render_verification_markdown(report)


def test_agreement_is_reported_when_both_backends_match():
    local = _local_engine()
    queries = [q for q in load_evalset() if q.query == "후라이팬"]
    same = [{"doc_id": h.doc_id, "score": h.score} for h in local.search("후라이팬")]

    es = ElasticsearchEngine(
        FakeClient(hits={"후라이팬": same}), load_catalog(), local.config, index="t"
    )
    report = verify(local, es, queries)
    assert not report.diverged
    assert report.local_mean == report.es_mean
    assert "갈린 질의가 없다" in render_verification_markdown(report)


def test_token_difference_is_recorded_even_without_divergence():
    """Kiwi ≠ nori는 정상이다. 토큰이 달라도 결과가 같으면 갈린 것이 아니다.

    그래도 토큰 차이는 기록한다 — 왜 갈렸는지 설명할 때의 유일한 단서다.
    """
    local = _local_engine()
    queries = [q for q in load_evalset() if q.query == "후라이팬"]
    same = [{"doc_id": h.doc_id, "score": h.score} for h in local.search("후라이팬")]

    es = ElasticsearchEngine(
        FakeClient(hits={"후라이팬": same}, tokens={"후라이팬": ["프라이", "팬"]}),
        load_catalog(),
        local.config,
        index="t",
    )
    (row,) = verify(local, es, queries).rows
    assert row.tokens_differ and not row.diverged
    assert row.nori_tokens == ["프라이", "팬"]


# --------------------------------------------------------------- 인증

def test_api_key_becomes_authorization_header(monkeypatch):
    monkeypatch.delenv("ES_API_KEY", raising=False)
    c = ESClient("http://x", api_key="abc123")
    assert c.authenticated
    assert c._auth_header == "ApiKey abc123"


def test_basic_auth_is_base64_of_user_colon_password(monkeypatch):
    for var in ("ES_API_KEY", "ES_USERNAME", "ES_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    expected = base64.b64encode(b"elastic:pw").decode()
    assert ESClient("http://x", username="elastic", password="pw")._auth_header == f"Basic {expected}"


def test_credentials_come_from_environment(monkeypatch):
    """명령줄에 비밀을 적지 않아도 되게 환경 변수를 읽는다."""
    monkeypatch.setenv("ES_API_KEY", "from-env")
    assert ESClient("http://x")._auth_header == "ApiKey from-env"


def test_no_credentials_means_no_authorization_header(monkeypatch):
    for var in ("ES_API_KEY", "ES_USERNAME", "ES_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    c = ESClient("http://x")
    assert not c.authenticated and c._auth_header is None


def test_authorization_header_is_attached_to_requests(monkeypatch):
    """헤더가 실제 요청에 붙는지 — 만들어만 두고 안 보내면 소용없다."""
    monkeypatch.delenv("ES_API_KEY", raising=False)
    seen = {}

    class FakeResponse:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        return FakeResponse()

    import searchclinic.es.client as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    ESClient("http://x", api_key="k").ping()
    assert seen["auth"] == "ApiKey k"
