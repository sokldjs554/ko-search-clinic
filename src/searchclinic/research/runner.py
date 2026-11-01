"""Controlled offline comparisons. Policy never receives evaluator labels."""
import json
import platform
import subprocess
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor.rules_plus import RulesPlusDoctor
from searchclinic.doctor.tools import ClinicExecutor
from searchclinic.evaluation.metrics import evaluate_all
from searchclinic.patch.ir import Prescription
from searchclinic.research.actions import ActionKind, Candidate, evidence_for
from searchclinic.research.calibration import freeze_config
from searchclinic.research.costs import CostRecord, MeasuredEngine
from searchclinic.research.detector import RuleDetector
from searchclinic.research.gate_adapter import GateAdapter
from searchclinic.research.metrics import summarize
from searchclinic.research.observations import observe
from searchclinic.research.policy import select_action
from searchclinic.research.splits import prepare_manifest, validate_splits, digest

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = ROOT / "artifacts/research/protocol.json"
PROTOCOL_VERSIONS = {
    "phase01-v1": (PROTOCOL_PATH, "6ec3b8dacba53b3bcd18704f2680567432dab531"),
    "phase01-v2": (ROOT / "artifacts/research/versions/phase01-v2/protocol.json",
                   "bb267e2853d5e66e9907fdf025ce651547765bca"),
}
POLICIES = ("no_repair", "always_typed_patch", "selective_rule")


def git_output(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load_protocol(protocol_version="phase01-v1"):
    if protocol_version not in PROTOCOL_VERSIONS:
        raise ValueError("unsupported protocol version")
    path, commit = PROTOCOL_VERSIONS[protocol_version]
    protocol = json.loads(path.read_text(encoding="utf-8"))
    frozen = json.loads(git_output("show", f"{commit}:{path.relative_to(ROOT).as_posix()}"))
    if protocol != frozen:
        raise ValueError("protocol hash differs from pre-experiment freeze")
    return protocol


def propose_candidates(engine, query, expected_cost=None):
    """Reuse v1 rules+ morphology rules with only public search diagnostics.

    Its private rule ladder is intentionally isolated here; no qrels, family or
    expected patch kinds are supplied. v1 regression tests protect its behavior.
    """
    start = perf_counter()
    tools = ClinicExecutor(engine, [])
    doctor = RulesPlusDoctor()
    doctor._query = query
    doctor._query_tokens = engine.analyzer.tokens(query)
    doctor._search_total = tools._tool_search_products(query)["total"]
    doctor._grep_total = tools._tool_grep_documents(query)["total"]
    doctor._similar = tools._tool_find_similar_tokens(doctor._probe)["similar"]
    prescriptions = [Prescription(target_query=query, **p) for p in doctor._ladder()]
    elapsed = (perf_counter() - start) * 1000
    return [Candidate(ActionKind.TYPED_PATCH, p, evidence_for(engine, p),
                      CostRecord(latency_ms=elapsed), expected_cost) for p in prescriptions]


def run_experiment(policy, manifest=None, protocol=None, protocol_version="phase01-v1"):
    if policy not in POLICIES:
        raise ValueError("unsupported Phase 1 policy")
    frozen = load_protocol(protocol_version)
    if protocol is not None and protocol != frozen:
        raise ValueError("protocol mismatch")
    protocol = frozen
    expected_cost = (CostRecord(**protocol["policy"]["expected_action_cost"])
                     if protocol_version == "phase01-v2" else None)
    docs, evalset = load_catalog(), load_evalset()
    expected = prepare_manifest(evalset, docs, protocol["seed"])
    manifest = expected if manifest is None else manifest
    validate_splits(manifest["rows"], evalset, docs)
    if manifest != expected:
        raise ValueError("manifest hash/split contract mismatch")
    freeze = freeze_config(manifest["rows"], protocol)
    start = perf_counter()
    engine = MeasuredEngine(docs)
    before = evaluate_all(engine, evalset)
    detector = RuleDetector(protocol["detector"])
    observations = {r["query"]: observe(engine, r["query"], r["query_id"], r["split"])
                    for r in manifest["rows"]}
    gate = GateAdapter(engine, evalset, min_gain=protocol["policy"]["min_gain"],
                       epsilon=protocol["policy"]["epsilon"])
    gate.budget.max_actions = protocol["policy"]["max_actions"]
    gate.budget.max_submits = protocol["policy"]["max_submits"]
    queries = []
    for eq in evalset:
        observation = observations[eq.query]
        detection = detector.detect(observation.policy_view())
        gate.start_session(eq.query)
        trace_start = len(gate.trace)
        query_start = perf_counter()
        calls_before, reindexes_before = engine.meter.search_calls, engine.meter.reindexes
        decision, intervened, events = "no_op", False, []
        should_diagnose = (policy == "always_typed_patch" or
                          policy == "selective_rule" and detection.predicted_failure is True)
        if should_diagnose:
            intervened = True
            candidates = propose_candidates(gate.engine, eq.query, expected_cost=expected_cost)
            if not candidates:
                decision = "abstain"
                events.append({"action": "abstain", "reason": "no_candidate"})
            while candidates:
                if policy == "selective_rule":
                    selected = select_action(detection, candidates, gate.budget,
                        weights=protocol["policy"]["weights"], min_gain=protocol["policy"]["min_gain"],
                        cost_semantics=protocol["policy"].get("cost_semantics", "measured-v1"))
                    decision = selected.action.value
                    events.append({"action": decision, "reason": selected.reason,
                                   "utility": selected.utility, "feedback": gate.feedback})
                    if protocol_version == "phase01-v2":
                        chosen = selected.candidate
                        events[-1].update(cost_semantics="expected-v2",
                            expected_cost=asdict(chosen.expected_cost) if chosen else None,
                            measured_candidate_generation_cost=asdict(chosen.cost) if chosen else None)
                    if selected.candidate is None:
                        break
                    candidate = selected.candidate
                    candidates.remove(candidate)
                else:
                    candidate = candidates.pop(0)
                    decision = candidate.action.value
                result = gate.submit(candidate)
                if result["accepted"] or result["reason"] in ("budget_exhausted", "gate_error"):
                    break
        elif policy == "selective_rule":
            decision = select_action(detection, [], gate.budget).action.value
        trace = gate.trace[trace_start:]
        elapsed = (perf_counter() - query_start) * 1000
        enriched = observation.model_copy(update={
            "family": eq.family, "baseline_ndcg": before[eq.query].ndcg,
            "baseline_recall": before[eq.query].recall})
        queries.append(dict(query_id=observation.query_id, query=eq.query, split="dev",
            family=eq.family, observation=enriched.model_dump(), detection=detection.model_dump(),
            decision=decision, intervened=intervened, policy_events=events, trace=trace,
            accepted=any(t["accepted"] for t in trace), submissions=gate.budget.used_submits,
            action_count=gate.budget.used_actions, before=asdict(before[eq.query]),
            costs=asdict(CostRecord(search_calls=engine.meter.search_calls - calls_before,
                reindexes=engine.meter.reindexes - reindexes_before, latency_ms=elapsed))))
    after = evaluate_all(gate.engine, evalset)
    for q in queries:
        q["after"] = asdict(after[q["query"]])
    elapsed = (perf_counter() - start) * 1000
    summary = summarize(queries, protocol["policy"]["epsilon"], protocol["detector"]["threshold"])
    result = dict(schema_version=1, policy=policy, dataset="controlled-v1/dev",
        heldout_status="not_collected", git_sha=git_output("rev-parse", "HEAD"),
        git_dirty=bool(git_output("status", "--porcelain", "--", "src", "tests", ".github")),
        source_hash=digest({str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
                           for p in sorted((ROOT / "src").rglob("*.py"))}),
        protocol_commit=PROTOCOL_VERSIONS[protocol_version][1],
        protocol_hash=digest(protocol), split_hash=manifest["split_hash"],
        corpus_hash=manifest["corpus_hash"], evalset_hash=manifest["evalset_hash"],
        environment={"python": platform.python_version(), "kiwipiepy": version("kiwipiepy"),
                     "kiwipiepy_model": version("kiwipiepy_model"), "pydantic": version("pydantic"),
                     "model": None}, seed=protocol["seed"], config=freeze,
        queries=queries, accepted_ledger=gate.accepted, summary=summary,
        costs=asdict(CostRecord(search_calls=engine.meter.search_calls,
            reindexes=engine.meter.reindexes, latency_ms=elapsed)),
        cost_scope="total includes observations, before/after evaluation and full gate",
        errors=[t["exception"] for t in gate.trace if "exception" in t])
    if protocol_version == "phase01-v2":
        result.update(schema_version=2, protocol_version=protocol_version,
                      policy_cost_semantics="expected-v2", posthoc_change=True)
    return result


def replay_signature(run):
    return {"policy": run["policy"], "split_hash": run["split_hash"],
        "queries": [{k: q[k] for k in ("query_id", "decision", "accepted", "submissions", "before", "after")}
                    for q in run["queries"]],
        "search_calls": run["costs"]["search_calls"], "reindexes": run["costs"]["reindexes"]}
