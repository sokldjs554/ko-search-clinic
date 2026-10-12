"""Offline CLI additions; legacy commands and artifact destinations are untouched."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.research.artifacts import write_artifact, write_report, render_report, compare_runs
from searchclinic.research.runner import ROOT, POLICIES, load_protocol, run_experiment
from searchclinic.research.splits import prepare_manifest, digest


def audit_state():
    from searchclinic.evaluation.baseline import compare, load_baseline
    from searchclinic.index.engine import SearchEngine
    from searchclinic.analysis.vectors import load_vectors_if_available
    docs, queries = load_catalog(), load_evalset()
    engine = SearchEngine(docs)
    result = compare(engine, queries, load_baseline(ROOT / "docs/BASELINE.json"))
    vectors = load_vectors_if_available()
    return dict(gate_baseline_pass=result.ok, docs=len(docs), queries=len(queries),
        healthy=sum(q.is_healthy for q in queries), failing=sum(not q.is_healthy for q in queries),
        families=sorted({q.family for q in queries if q.family}),
        vector_model=vectors.model if vectors is not None else None,
        vector_tokens=len(vectors) if vectors is not None else None,
        llm_reexecuted=False, elasticsearch_reexecuted=False,
        audit_document="docs/research/CURRENT_STATE_AUDIT.md")


def _run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]


def run_command(args):
    root = Path(args.root)
    try:
        protocol = load_protocol()
        if args.research_command == "audit":
            result = audit_state()
            write_artifact(root / "audit" / ("audit-" + _run_id() + ".json"), result)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["gate_baseline_pass"] else 1
        manifest_path = root / "splits/controlled-v1.json"
        if args.research_command == "prepare":
            manifest = prepare_manifest(load_evalset(), load_catalog(), protocol["seed"])
            if manifest_path.exists():
                if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
                    raise ValueError("existing manifest differs; overwrite refused")
            else:
                write_artifact(manifest_path, manifest)
            print(f"prepared {manifest_path}; counts={manifest['counts']}")
        elif args.research_command in ("run", "baseline"):
            if not manifest_path.exists():
                raise ValueError("run research prepare first")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            policies = POLICIES if args.research_command == "baseline" else [args.policy]
            for policy in policies:
                result = run_experiment(policy, manifest=manifest)
                path = root / "runs" / (policy + "-" + _run_id() + ".json")
                write_artifact(path, result)
                write_artifact(root / "observations" / path.name,
                               [q["observation"] for q in result["queries"]])
                write_artifact(root / "costs" / path.name, result["costs"])
                print(f"executed {policy}; artifact={path}", flush=True)
        elif args.research_command == "report":
            paths = sorted((root / "runs").glob("*.json"))
            runs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
            output = Path(args.output) if args.output else root / "summaries/RESULTS.md"
            text = render_report(runs)
            write_report(output, text)
            write_artifact(root / "summaries" / ("comparison-" + digest(runs)[:16] + ".json"),
                           compare_runs(runs))
            print(f"generated {output}")
        return 0
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"research stopped: {exc}")
        return 1


def add_parser(subparsers):
    parser = subparsers.add_parser("research", help="실패 탐지·선택 복구 오프라인 연구")
    commands = parser.add_subparsers(dest="research_command", required=True)
    for name in ("audit", "prepare", "baseline", "run", "report"):
        command = commands.add_parser(name)
        command.add_argument("--root", default="artifacts/research")
        if name == "run":
            command.add_argument("--policy", choices=POLICIES, default="selective_rule")
        if name == "report":
            command.add_argument("--output")
        command.set_defaults(func=run_command)
