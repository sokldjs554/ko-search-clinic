"""Public publication must not inherit private strings or per-query records."""
import importlib.util
import json
from pathlib import Path

import pytest

from test_v5_comparison import compare


def exporter():
    path=Path(__file__).resolve().parents[1]/'scripts/export_v5_live_summary.py'
    spec=importlib.util.spec_from_file_location('v5_export',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_aggregate_export_is_numeric_whitelist_not_recursive_record_copy():
    report=compare()
    report['scores']['summaries']['pair:1']['overall']['private_query']='DO_NOT_PUBLISH'
    report['arms']['pair:1']['selected']={'DO_NOT_PUBLISH':'secret'}
    report['arms']['pair:1']['reason_counts']['DO_NOT_PUBLISH']=1
    report['costs']['private_raw']='DO_NOT_PUBLISH'
    exported=exporter().aggregate_report(report)
    encoded=json.dumps(exported)
    assert 'DO_NOT_PUBLISH' not in encoded
    assert 'q1' not in encoded and 'q2' not in encoded
    assert exported['arms']['pair:1']['metrics']['overall']['ndcg10']==1.0
    assert exported['arms']['pair:1']['apply_count']==2
    assert exported['arms']['no_repair']['normal_regression_count']==0
    assert exported['arms']['no_repair']['useful_candidate_false_hold_count'] is None
    assert 'per_query' not in encoded


def test_unknown_strings_cannot_be_published_as_metrics():
    report=compare();report['scores']['summaries']['pair:1']['overall']['ndcg10']='secret text'
    with pytest.raises(ValueError,match='numeric'):
        exporter().aggregate_report(report)
