"""Review regressions; every provider response here is a synthetic HTTP fixture."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from searchclinic.research_v5 import comparison, pipeline, evidence, transport
from test_v5_comparison import inputs, trials_for
from test_v5_transport import bundle as transport_bundle, response, approval


def test_summary_alone_cannot_authorize_final_semantic_results():
    bundle, _, _ = inputs()
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='gpt_generated', phase='final')
    attestation = pipeline.freeze(dict(input_hash=bundle['sha256'], protocol_hash=protocol['sha256'],
                                      **{k: True for k in comparison.ATTESTATIONS}))
    summary = dict(transport='provider_transport', input_hash=bundle['sha256'],
                   provider_calls_executed=1, status='stopped', valid_verdicts=0)
    with pytest.raises(ValueError, match='evidence'):
        comparison.assemble_comparison(bundle, trials_for(bundle), protocol=protocol,
                                       attestations=attestation, transport_summary=summary)


def loader():
    spec = importlib.util.find_spec('searchclinic.research_v5.run_evidence')
    assert spec is not None, 'Raw transport evidence verifier is missing'
    return __import__('searchclinic.research_v5.run_evidence', fromlist=['load_run'])


def run_fixture(tmp_path, monkeypatch, stopped=False):
    monkeypatch.setattr(transport, 'WORK_ROOT', tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-secret')
    bundle = pipeline.freeze(transport_bundle())
    plan = transport.build_plan(bundle)
    calls = iter(plan['body']['calls'])
    def handler(request):
        call = next(calls)
        if stopped:
            raise httpx.ReadTimeout('synthetic timeout')
        return httpx.Response(200, json=response(call, id='resp_fixture_'+call['call_id']))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport.run_plan(plan, tmp_path/'run', approval=approval(plan), client=client)
    return bundle, tmp_path/'run'


def test_stopped_run_keeps_full_denominators_and_is_never_final(tmp_path, monkeypatch):
    api = loader()
    bundle, folder = run_fixture(tmp_path, monkeypatch, stopped=True)
    checked = api.load_run(folder, bundle)
    assert checked['body']['summary']['status'] == 'stopped'
    assert checked['body']['summary']['unattempted_calls'] == 11
    assert len(checked['body']['trials']) == 6
    assert all(v is None for t in checked['body']['trials'] for row in t['verdicts'].values() for v in row)
    with pytest.raises(ValueError, match='complete'):
        api.validate_run(checked, bundle, require_complete=True)


@pytest.mark.parametrize('tamper', ['export', 'request', 'raw_model', 'outcome', 'count'])
def test_evidence_verification_rejects_disconnected_exports_and_outcomes(tmp_path, monkeypatch, tamper):
    api = loader()
    bundle, folder = run_fixture(tmp_path, monkeypatch)
    if tamper == 'export':
        p = folder/'verdicts-pair-repeat-1.json'; d=json.loads(p.read_text(encoding="utf-8"));d['q1'][0]=None
    elif tamper == 'request':
        p=folder/'calls/001/request.json';d=json.loads(p.read_text(encoding="utf-8"));d['candidate_index']=99
    elif tamper == 'raw_model':
        p=folder/'calls/001/raw-response.json';d=json.loads(p.read_text(encoding="utf-8"));raw=json.loads(d['body']);raw['model']='different';d['body']=json.dumps(raw)
    elif tamper == 'outcome':
        p=folder/'calls/001/outcome.json';d=json.loads(p.read_text(encoding="utf-8"));d['verdict']=None
    else:
        p=folder/'summary.json';d=json.loads(p.read_text(encoding="utf-8"));d['provider_calls_executed']=1
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError):api.load_run(folder,bundle)


def test_valid_response_exports_are_rederived_from_raw_body(tmp_path, monkeypatch):
    api=loader();bundle,folder=run_fixture(tmp_path,monkeypatch)
    result=api.load_run(folder,bundle)
    assert len(result['body']['trials']) == 6
    assert result['body']['summary']['valid_verdicts']==12
    assert api.validate_run(result,bundle,require_complete=True)['trials']==result['body']['trials']


def comparison_cli():
    path=Path(__file__).parents[1]/'scripts/compare_v5_conditions.py'
    spec=importlib.util.spec_from_file_location('compare_cli',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('outside', ['docs/result.json','src/searchclinic/web/result.json','artifacts/new.json','../outside.json'])
def test_comparison_private_destination_rejects_public_paths(tmp_path,monkeypatch,outside):
    cli=comparison_cli();monkeypatch.setattr(cli,'ROOT',tmp_path)
    assert hasattr(cli,'private_output'), 'Comparison private output guard is missing'
    with pytest.raises(ValueError):cli.private_output(tmp_path/outside)


def test_comparison_private_destination_rejects_symlink_escape(tmp_path,monkeypatch):
    cli=comparison_cli();monkeypatch.setattr(cli,'ROOT',tmp_path)
    assert hasattr(cli,'private_output'), 'Comparison private output guard is missing'
    (tmp_path/'work').mkdir();(tmp_path/'work/escape').symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError):cli.private_output(tmp_path/'work/escape/result.json')
    assert cli.private_output(tmp_path/'work/new.json')==tmp_path/'work/new.json'


def test_created_recipient_uses_platform_specific_permission_verification(tmp_path,monkeypatch):
    monkeypatch.setattr(evidence,'WORK_ROOT',tmp_path)
    assert hasattr(evidence,'check_key_permissions'), 'Platform key permission policy missing'
    evidence.create_recipient(tmp_path/'key.json')
    evidence.check_key_permissions(tmp_path/'key.json')


def test_windows_acl_failure_happens_before_private_bytes_written(tmp_path,monkeypatch):
    monkeypatch.setattr(evidence,'WORK_ROOT',tmp_path)
    assert hasattr(evidence,'WINDOWS'), 'Platform key permission policy missing'
    monkeypatch.setattr(evidence,'WINDOWS',True)
    def fail(path, *, secure=False):
        assert path.read_bytes()==b''
        raise ValueError('ACL setup unavailable')
    monkeypatch.setattr(evidence,'windows_key_acl',fail)
    with pytest.raises(ValueError):evidence.create_recipient(tmp_path/'key.json')
    assert (tmp_path/'key.json').read_bytes()==b''


@pytest.mark.parametrize('module_variable', ['PSModulePath', 'PSMODULEPATH'])
def test_windows_powershell_does_not_inherit_core_module_search_path(tmp_path, monkeypatch, module_variable):
    from types import SimpleNamespace
    monkeypatch.setattr(evidence.os, 'environ', {module_variable:'PowerShell-7-only-modules', 'PATH':'system-tools'})
    def execute(command, **kwargs):
        child_environment = kwargs.get('env')
        assert child_environment is not None
        assert all(key.casefold() != 'psmodulepath' for key in child_environment)
        assert child_environment['PATH'] == 'system-tools'
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(evidence.subprocess,'run',execute)
    evidence.windows_key_acl(tmp_path/'empty',secure=True)
