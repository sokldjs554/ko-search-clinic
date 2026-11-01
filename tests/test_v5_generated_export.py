"""Public cost export excludes provider text and uses recorded usage."""
import importlib.util
import json
from pathlib import Path

import pytest


def exporter():
    p=Path(__file__).resolve().parents[1]/'scripts/export_v5_generated_summary.py'
    assert p.exists(), 'generated export missing'
    spec=importlib.util.spec_from_file_location('generated_export',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_usage_is_recomputed_without_copying_private_strings():
    row={'usage':{'input_tokens':100,'output_tokens':50},'latency_ms':2.,'status':'valid','private':'DO_NOT_PUBLISH'}
    summary={'provider_calls_executed':1,'usage_cost_estimate_usd':.00012,'latency_ms':3.,'private':'DO_NOT_PUBLISH'}
    result=exporter().usage_summary([row],summary)
    assert result['usage_cost_estimate_usd']==.00012
    assert result['provider_calls']==1
    assert 'DO_NOT_PUBLISH' not in json.dumps(result)
    assert result['actual_invoice_usd'] is None


def test_usage_mismatch_is_not_published():
    row={'usage':{'input_tokens':100,'output_tokens':50},'latency_ms':2.,'status':'valid'}
    summary={'provider_calls_executed':1,'usage_cost_estimate_usd':1.,'latency_ms':3.}
    with pytest.raises(ValueError,match='usage'):
        exporter().usage_summary([row],summary)
