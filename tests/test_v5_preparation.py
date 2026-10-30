"""Offline preparation keeps replay outcomes outside fixed judge inputs."""
import importlib
import importlib.util
import json
import socket

import pytest

from searchclinic.corpus.catalog import Document
from searchclinic.corpus.evalset import EvalQuery
from searchclinic.research_v5.pipeline import verify


def preparation():
    assert importlib.util.find_spec("scripts.prepare_v5_development") is not None, "Offline preparation is missing"
    return importlib.import_module("scripts.prepare_v5_development")


def rx(terms=None):
    return dict(target_query="alpha", diagnosis_family="synonym_gap",
                reasoning="Saved public candidate explanation.",
                synonym_groups=[dict(terms=terms or ["alpha", "beta"])])


def saved_rows():
    # None of these replay-only values may cross into a public artifact.
    return [dict(query_id="q1", query="alpha", qrels={"a00": 2}, stratum="failure",
                 scores={"ndcg10": 1.0}, candidates=[dict(prescription=rx(), target_gain=1.0),
                                                     dict(prescription=rx(["alpha", "invented"]))]),
            dict(query_id="q2", query="healthy", qrels={"z": 1}, stratum="healthy", candidates=[])]


class Analyzer:
    def tokens(self, text):
        return text.split()


class Engine:
    created = []

    def __init__(self, docs):
        self.analyzer = Analyzer()
        self.docs = docs
        self.searches = []
        type(self).created.append(self)

    def search(self, query, k):
        self.searches.append((query, k))
        return [object()] * 12


@pytest.fixture
def prepared_inputs(monkeypatch):
    api = preparation()
    Engine.created = []
    docs = [Document("z", "healthy", "catalog item", "sample")]
    docs += [Document(f"a{i:02}", "beta", f"item {i}", "sample") for i in reversed(range(12))]
    monkeypatch.setattr(api, "load_saved_candidates", saved_rows)
    monkeypatch.setattr(api, "load_catalog", lambda: docs)
    monkeypatch.setattr(api, "SearchEngine", Engine)
    monkeypatch.setattr(api, "load_evalset", lambda: [EvalQuery("alpha", {"a00": 2}, "synonym_gap"),
                                                     EvalQuery("healthy", {"z": 1})])
    return api


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_preparation_has_fixed_candidates_all_queries_and_sorted_bounded_evidence(prepared_inputs, tmp_path):
    api = prepared_inputs
    destination = tmp_path / "prepared"
    summary = api.prepare(destination)
    bundle = verify(read(destination / "candidates.json"))
    assert set(bundle) == {"version", "model_id", "min_confidence", "seed", "documents", "records"}
    assert bundle["version"] == "v5" and bundle["model_id"] == "gpt-4.1-mini-2025-04-14"
    assert bundle["min_confidence"] == .8 and bundle["seed"] == 20261030
    records = bundle["records"]
    assert [r["context"]["query_id"] for r in records] == ["q1", "q2"]
    assert [len(r["candidates"]) for r in records] == [2, 0]
    assert records[0]["candidates"] == [rx(), rx(["alpha", "invented"])]
    context = records[0]["context"]
    assert context["search_total"] == context["observation"]["result_count"] == 10
    assert [d["doc_id"] for d in context["documents"]] == [f"a{i:02}" for i in range(10)]
    assert context["grep_total"] == 12
    assert all(r["generation_error"] is None for r in records)
    assert read(destination / "verdicts-empty.json") == {"q1": [], "q2": []}
    assert len(Engine.created) == 1 and Engine.created[0].searches == [("alpha", 10), ("healthy", 10)]
    assert summary["candidates"] == 2 and summary["proposed_calls"] == 12
    audit = verify(read(destination / "preparation.json"))
    assert audit["study_status"] == "retrospective_controlled_development_only"
    assert audit["original_context_reproduced"] is False
    assert audit["candidate_checks"]["q1"][0]["literal_validation_error"] is None
    assert "literal evidence" in audit["candidate_checks"]["q1"][1]["literal_validation_error"]


def test_public_files_exclude_outcomes_and_labels_load_only_after_requests_saved(prepared_inputs, monkeypatch, tmp_path):
    destination = tmp_path / "prepared"
    private_queries = [EvalQuery("alpha", {"a00": 2}, "synonym_gap"), EvalQuery("healthy", {"z": 1})]

    def delayed_labels():
        assert all((destination / f"requests-{condition}.json").exists() for condition in ("pair", "context", "rubric"))
        assert (destination / "candidates.json").exists()
        return private_queries

    monkeypatch.setattr(prepared_inputs, "load_evalset", delayed_labels)
    prepared_inputs.prepare(destination)
    forbidden = {"qrels", "stratum", "scores", "target_gain", "ndcg10", "accepted", "historical_accepted"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    for path in destination.glob("*.json"):
        public = read(path)
        check(public)
        for forbidden_literal in ('"qrels"', '"stratum"', '"scores"'):
            assert forbidden_literal not in path.read_text(encoding="utf-8")
    private = read(destination / "private" / "labels.json")
    assert private["qrels"] == {"q1": {"a00": 2}, "q2": {"z": 1}}
    assert [q["stratum"] for q in private["queries"]] == ["failure", "healthy"]
    manifest = read(destination / "private" / "labels-manifest.json")
    assert manifest["labels_sha256"] == api_file_sha(destination / "private" / "labels.json")


def api_file_sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_requests_share_candidate_hashes_and_budget_is_not_a_tokenizer(prepared_inputs, tmp_path):
    destination = tmp_path / "prepared"
    prepared_inputs.prepare(destination)
    hashes = {}
    bodies = {}
    for condition in ("pair", "context", "rubric"):
        request_set = verify(read(destination / f"requests-{condition}.json"))
        assert request_set["model_id"] == "gpt-4.1-mini-2025-04-14"
        assert len(request_set["records"]) == 2
        for row in request_set["records"]:
            key = (row["query_id"], row["candidate_index"])
            hashes.setdefault(key, set()).add(row["request"]["candidate_hash"])
            bodies.setdefault(key, set()).add(row["request"]["body"])
            assert row["input_token_upper_bound"] == len(row["request"]["body"].encode("utf-8")) + 256
            assert row["budget_status"] == "ready"
    assert all(len(values) == 1 for values in hashes.values())
    assert all(len(values) == 3 for values in bodies.values())
    proposal = read(destination / "proposal.json")
    assert proposal["proposed_calls"] == 12 and proposal["repeats"] == 2
    assert proposal["max_input_tokens"] == 12000 and proposal["max_output_tokens"] == 2000
    assert proposal["maximum_cost_usd"] == .096
    assert proposal["input_usd_per_million_tokens"] == .4
    assert proposal["output_usd_per_million_tokens"] == 1.6
    assert proposal["automatic_retries"] == 0 and proposal["provider_calls_executed"] == 0
    assert proposal["model_availability_verified"] is False


def test_large_requests_are_flagged_without_truncation(prepared_inputs, monkeypatch, tmp_path):
    long_description = "가" * 5000
    monkeypatch.setattr(prepared_inputs, "load_catalog", lambda: [Document("d", "beta", long_description, "sample")])
    destination = tmp_path / "prepared"
    prepared_inputs.prepare(destination)
    contextual = verify(read(destination / "requests-context.json"))
    first = contextual["records"][0]
    assert first["input_token_upper_bound"] > 12000
    assert first["budget_status"] == "request_too_large"
    assert long_description in first["request"]["body"]


def test_output_directory_is_write_once_and_network_is_never_opened(prepared_inputs, monkeypatch, tmp_path):
    def prohibited(*args, **kwargs):
        raise AssertionError("Network attempted during offline preparation")

    monkeypatch.setattr(socket, "socket", prohibited)
    destination = tmp_path / "prepared"
    prepared_inputs.prepare(destination)
    before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*.json")}
    with pytest.raises(FileExistsError):
        prepared_inputs.prepare(destination)
    after = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*.json")}
    assert before == after and len(Engine.created) == 1


def test_raw_loader_uses_only_source_identity_and_prescription_fields(tmp_path):
    api = preparation()
    path = tmp_path / "saved.json"
    row = dict(query_id="q1", query="alpha", final_label="failure", qrels={"d": 2},
               trace=[dict(prescription=rx(), accepted=True, evidence={"score": 3})])
    path.write_text(json.dumps({"queries": [row]}), encoding="utf-8")
    loaded = api.load_saved_candidates([path])
    assert loaded == [dict(query_id="q1", query="alpha", candidates=[dict(prescription=rx())])]
    row["trace"][0]["prescription"]["target_query"] = "swapped"
    path.write_text(json.dumps({"queries": [row]}), encoding="utf-8")
    with pytest.raises(ValueError, match="target"):
        api.load_saved_candidates([path])
