"""ES 렌더러와 CLI 스모크 테스트."""

import json

from searchclinic.analysis.config import (
    AnalyzerConfig,
    CompoundExpansion,
    SynonymGroup,
    UserWord,
)
from searchclinic.cli import main
from searchclinic.patch.es_render import render_es_json, to_es_settings


def _full_config() -> AnalyzerConfig:
    return AnalyzerConfig(
        user_words=[UserWord(form="아답터")],
        synonym_groups=[SynonymGroup(terms=["프라이팬", "후라이팬"])],
        compound_expansions=[CompoundExpansion(word="물티슈", parts=["물", "티슈"])],
    )


def test_es_settings_map_patches_one_to_one():
    settings = to_es_settings(_full_config())
    tok = settings["settings"]["index"]["analysis"]["tokenizer"]["clinic_korean_tokenizer"]
    assert tok["type"] == "nori_tokenizer"
    assert tok["decompound_mode"] == "mixed"
    assert "아답터" in tok["user_dictionary_rules"]  # UserWord
    assert "물티슈 물 티슈" in tok["user_dictionary_rules"]  # CompoundExpansion
    syn = settings["settings"]["index"]["analysis"]["filter"]["clinic_synonyms"]
    assert syn["synonyms"] == ["후라이팬 => 프라이팬"]  # SynonymGroup(대표형 매핑)


def test_es_settings_without_synonyms_omits_filter():
    settings = to_es_settings(AnalyzerConfig(user_words=[UserWord(form="아답터")]))
    analysis = settings["settings"]["index"]["analysis"]
    assert "clinic_synonyms" not in analysis["filter"]
    assert "clinic_synonyms" not in analysis["analyzer"]["clinic_korean"]["filter"]


def test_render_es_json_is_valid_json():
    parsed = json.loads(render_es_json(_full_config()))
    assert parsed["mappings"]["properties"]["name"]["analyzer"] == "clinic_korean"


# ------------------------------------------------------------------ CLI 스모크


def test_cli_analyze(capsys):
    assert main(["analyze", "아답터"]) == 0
    out = capsys.readouterr().out
    assert "아답터" in out or "답" in out  # 쓰레기 분해가 보인다


def test_cli_search(capsys):
    assert main(["search", "프라이팬"]) == 0
    assert "P001" in capsys.readouterr().out


def test_cli_evaluate(capsys):
    assert main(["evaluate"]) == 0
    out = capsys.readouterr().out
    assert "제로결과율" in out


def test_cli_demo_trap(capsys):
    assert main(["demo-trap"]) == 0
    out = capsys.readouterr().out
    assert "기각" in out and "채택" in out


def test_cli_diagnose_scripted(capsys):
    assert main(["diagnose", "후라이팬", "--engine", "scripted"]) == 0
    out = capsys.readouterr().out
    assert "✅ 치유" in out


def test_cli_heal_writes_outputs(tmp_path, capsys):
    report = tmp_path / "report.md"
    ledger = tmp_path / "ledger.json"
    es = tmp_path / "es.json"
    assert main([
        "heal", "--engine", "scripted",
        "--output", str(report), "--ledger", str(ledger), "--es-output", str(es),
    ]) == 0
    # encoding을 명시하지 않으면 한국어 Windows에서 cp949로 읽혀 깨진다.
    # CLI는 항상 UTF-8로 쓰므로 읽는 쪽도 UTF-8로 고정한다 (실측으로 확인된 실패).
    assert "치유율" in report.read_text(encoding="utf-8")
    entries = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(entries) == 10
    assert all("evidence" in e for e in entries)
    es_settings = json.loads(es.read_text(encoding="utf-8"))
    assert "analysis" in es_settings["settings"]["index"]
