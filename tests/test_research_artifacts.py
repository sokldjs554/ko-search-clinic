import json
import pytest


def test_artifact_cannot_overwrite_a_prior_run(tmp_path):
    from searchclinic.research.artifacts import write_artifact
    p = tmp_path / "run.json"
    write_artifact(p, {"ndcg": 0.5})
    with pytest.raises(FileExistsError):
        write_artifact(p, {"ndcg": 0.9})
    assert json.loads(p.read_text(encoding="utf-8"))["ndcg"] == 0.5
    with pytest.raises(ValueError):
        write_artifact(tmp_path / "invalid.json", {"value": float("nan")})


def test_generated_report_reads_actual_artifact_values():
    from searchclinic.research.runner import run_experiment
    from searchclinic.research.artifacts import render_report
    run = run_experiment("no_repair")
    text = render_report([run])
    assert f"{run['summary']['failing_ndcg_after']:.4f}" in text
    assert str(run["costs"]["search_calls"]) in text
    assert "controlled-v1/dev" in text and "held-out" in text


def test_cli_prepares_and_runs_json_artifacts_without_api_keys(tmp_path, monkeypatch):
    from searchclinic.cli import main
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["research", "prepare", "--root", str(tmp_path)]) == 0
    assert main(["research", "run", "--policy", "no_repair", "--root", str(tmp_path)]) == 0
    assert main(["research", "report", "--root", str(tmp_path)]) == 0
    runs = list((tmp_path / "runs").glob("*.json"))
    assert len(runs) == 1 and len(json.loads(runs[0].read_text(encoding="utf-8"))["queries"]) == 36
    assert (tmp_path / "summaries/RESULTS.md").exists()


def test_cli_keeps_legacy_search_command(capsys):
    from searchclinic.cli import main
    assert main(["search", "프라이팬"]) == 0
    assert "프라이팬" in capsys.readouterr().out


def test_comparison_rejects_a_different_query_order_or_seed():
    from searchclinic.research.runner import run_experiment
    from searchclinic.research.artifacts import compare_runs
    from copy import deepcopy
    a = run_experiment("no_repair")
    a["policy"] = "always_typed_patch"
    b = deepcopy(a)
    b["policy"] = "selective_rule"
    b["seed"] += 1
    with pytest.raises(ValueError, match="seed"):
        compare_runs([a, b])


def test_comparison_cannot_mix_different_qrels_hashes():
    from searchclinic.research.runner import run_experiment
    from searchclinic.research.artifacts import compare_runs
    from copy import deepcopy
    a = run_experiment("no_repair")
    a["policy"] = "always_typed_patch"
    b = deepcopy(a)
    b["policy"] = "selective_rule"
    b["evalset_hash"] = "altered-qrels"
    with pytest.raises(ValueError, match="evalset_hash"):
        compare_runs([a, b])


def test_duplicate_policy_runs_cannot_silently_replace_evidence():
    from searchclinic.research.artifacts import compare_runs
    with pytest.raises(ValueError, match="duplicate"):
        compare_runs([{"policy": "selective_rule"}, {"policy": "selective_rule"}])
