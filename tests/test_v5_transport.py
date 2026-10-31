"""Free transport contract tests: HTTP is intercepted, never a paid request."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from searchclinic.research_v5.pipeline import freeze, verify
from test_v5_pipeline import bundle as fixture_bundle


def bundle():
    value = fixture_bundle()
    value["model_id"] = "gpt-4.1-mini-2025-04-14"
    return value


@pytest.fixture
def api(tmp_path, monkeypatch):
    assert importlib.util.find_spec('searchclinic.research_v5.transport') is not None, 'transport implementation is missing'
    module = importlib.import_module('searchclinic.research_v5.transport')
    monkeypatch.setattr(module, 'WORK_ROOT', tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-secret-never-log')
    return module


def plan(api):
    return api.build_plan(freeze(bundle()))


def approval(sealed):
    body = verify(sealed)
    return dict(approved=True, plan_hash=sealed['sha256'], model_id=body['model_id'],
                max_calls=body['call_count'], max_cost_usd=body['maximum_cost_usd'])


def response(call, **changes):
    patches = json.loads(call['request']['body'])['patches']
    assessments = [dict(patch_id=p['patch_id'], relation='uncertain', same_referent=None,
                        scope_preserved=None, context_supported=None, confidence=0.0,
                        reasoning='Synthetic test fixture, no semantic finding.', citations=[]) for p in patches]
    result = dict(id='resp_fixture', status='completed', model=call['payload']['model'],
                  usage=dict(input_tokens=100, output_tokens=50, total_tokens=150),
                  output=[dict(type='message', content=[dict(type='output_text', text=json.dumps({'assessments': assessments}))])])
    result.update(changes)
    return result


def test_plan_binds_all_conditions_repeats_and_full_schema_overhead(api):
    sealed = plan(api)
    body = verify(sealed)
    assert body['call_count'] == 12 and body['maximum_cost_usd'] == .096
    assert body['pricing_snapshot']['current_pricing_verified'] is False
    assert len({c['call_id'] for c in body['calls']}) == 12
    assert {(c['condition'], c['repeat']) for c in body['calls']} == {(x, y) for x in ('pair','context','rubric') for y in (1,2)}
    for call in body['calls']:
        assert call['input_token_upper_bound'] >= len(json.dumps(call['payload'], ensure_ascii=False).encode())
        schema = call['payload']['text']['format']['schema']
        def check(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    assert node['additionalProperties'] is False
                    assert set(node['required']) == set(node['properties'])
                assert 'default' not in node
                for value in node.values(): check(value)
            elif isinstance(node, list):
                for value in node: check(value)
        check(schema)
    changed = bundle(); changed['records'][0]['candidates'][0]['reasoning'] += ' changed'
    assert api.build_plan(freeze(changed))['sha256'] != sealed['sha256']


def test_reservation_and_request_exist_before_http_and_exports_are_aligned(api, tmp_path):
    sealed = plan(api); calls = verify(sealed)['calls']; observed = []
    destination = tmp_path/'run'
    def handler(request):
        call = calls[len(observed)]
        evidence = destination/'calls'/call['call_id']
        assert json.loads((evidence/'reservation.json').read_text(encoding="utf-8"))['reserved_cost_usd'] == .008
        assert (evidence/'request.json').exists()
        assert request.url == 'https://api.openai.com/v1/responses'
        assert request.method == 'POST'
        assert json.loads(request.content) == call['payload']
        observed.append(call)
        return httpx.Response(200, json=response(call))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.run_plan(sealed, destination, approval=approval(sealed), client=client)
    assert result['completed_calls'] == 12 and result['transport'] == 'provider_transport'
    assert len(observed) == 12
    for condition in ('pair','context','rubric'):
        for repeat in (1,2):
            verdicts = json.loads((destination/f'verdicts-{condition}-repeat-{repeat}.json').read_text(encoding="utf-8"))
            assert set(verdicts) == {'q1','q2'}
            assert all(v[0]['model_id'] == 'gpt-4.1-mini-2025-04-14' for v in verdicts.values())
    assert 'sk-secret-never-log' not in ''.join(p.read_text(encoding="utf-8") for p in destination.rglob('*.json'))
    with pytest.raises(ValueError, match='already|repeat|exist'):
        api.run_plan(sealed, tmp_path/'another', approval=approval(sealed))


@pytest.mark.parametrize('change', ['hash','cost','count','model','unapproved'])
def test_approval_must_match_exact_plan_before_any_io(api, tmp_path, change):
    sealed = plan(api); approved = approval(sealed)
    field, value = {'hash': ('plan_hash','0'*64), 'cost': ('max_cost_usd',.001), 'count': ('max_calls',13),
                    'model': ('model_id','different'), 'unapproved': ('approved',False)}[change]
    approved[field] = value
    with pytest.raises(ValueError, match='approval'):
        api.run_plan(sealed, tmp_path/'run', approval=approved)
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('kind', ['refusal','incomplete','error','missing_usage','bad_usage','wrong_model','malformed','coverage'])
def test_bad_responses_are_held_and_durable(api, tmp_path, kind):
    sealed = plan(api); calls = verify(sealed)['calls']; first = calls[0]
    raw = response(first)
    if kind == 'refusal': raw['output'][0]['content'] = [dict(type='refusal', refusal='No')]
    elif kind == 'incomplete': raw['status'] = 'incomplete'
    elif kind == 'error': raw['error'] = {'message':'failure'}
    elif kind == 'missing_usage': del raw['usage']
    elif kind == 'bad_usage': raw['usage']['input_tokens'] = True
    elif kind == 'wrong_model': raw['model'] = 'unexpected-model'
    elif kind == 'malformed': raw['output'][0]['content'][0]['text'] = 'not JSON'
    elif kind == 'coverage': raw['output'][0]['content'][0]['text'] = '{"assessments": []}'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw))) as client:
        result = api.run_plan(sealed, tmp_path/'run', approval=approval(sealed), client=client)
    evidence = tmp_path/'run'/'calls'/first['call_id']
    outcome = json.loads((evidence/'outcome.json').read_text(encoding="utf-8"))
    assert outcome['verdict'] is None and outcome['status'] != 'valid'
    assert (evidence/'raw-response.json').exists()
    assert result['valid_verdicts'] == 0


def test_timeout_is_not_retried_and_secret_exception_is_redacted(api, tmp_path):
    sealed = plan(api); observed=[]
    def handler(request):
        observed.append(request)
        raise httpx.ReadTimeout('sk-secret-never-log leaked body', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.run_plan(sealed, tmp_path/'run', approval=approval(sealed), client=client)
    assert len(observed) == 1 and result['reserved_cost_usd'] == .008
    assert result['status'] == 'stopped'
    text = ''.join(p.read_text(encoding="utf-8") for p in (tmp_path/'run').rglob('*.json'))
    assert 'sk-secret-never-log' not in text and 'leaked body' not in text


def test_free_mock_needs_no_key_and_is_explicitly_synthetic(api, tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    result = api.run_plan(plan(api), tmp_path/'mock', mock=True)
    assert result['transport'] == 'mocked_transport' and result['provider_calls_executed'] == 0
    assert result['completed_calls'] == 12 and result['usage_cost_estimate_usd'] == 0
    verdicts = json.loads((tmp_path/'mock'/'verdicts-pair-repeat-1.json').read_text(encoding="utf-8"))
    assert verdicts['q1'][0]['model_id'].startswith('mock:')


def test_oversize_and_resealed_tampering_are_rejected(api, tmp_path):
    raw = bundle(); raw['records'][0]['candidates'][0]['synonym_groups'][0]['terms'].append('가'*5000)
    with pytest.raises(ValueError, match='oversize|input'):
        api.build_plan(freeze(raw))
    sealed = plan(api); altered = verify(sealed); altered['calls'][0]['payload']['model'] = 'other'
    with pytest.raises(ValueError, match='plan'):
        api.run_plan(freeze(altered), tmp_path/'run', mock=True)


def test_model_access_is_separate_get_and_no_key_in_output(api):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'id':'fixture-model', 'object':'model'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.check_model_access('fixture-model', client=client)
    assert result['accessible'] is True and result['generation_calls'] == 0
    assert len(requests) == 1 and requests[0].method == 'GET'


def test_cli_installs_label_guard_before_application_import_and_is_free_by_default(tmp_path):
    script = Path(__file__).parents[1]/'scripts/run_v5_judges.py'
    result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and '--execute' in result.stdout
    source = script.read_text(encoding="utf-8")
    assert source.index('protect(') < source.index('from searchclinic.research_v5.transport import')


def test_configured_price_cannot_be_applied_to_another_model(api):
    raw = bundle(); raw['model_id'] = 'arbitrary-expensive-model'
    with pytest.raises(ValueError, match='model'):
        api.build_plan(freeze(raw))


def test_missing_key_does_not_claim_or_create_run(api, tmp_path, monkeypatch):
    sealed = plan(api)
    monkeypatch.delenv('OPENAI_API_KEY')
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        api.run_plan(sealed, tmp_path/'run', approval=approval(sealed))
    assert not list(tmp_path.iterdir())


def test_response_credential_echo_is_scrubbed_even_if_json_escaped(api, tmp_path):
    sealed = plan(api)
    escaped = ''.join('\\u%04x' % ord(c) for c in 'sk-secret-never-log')
    raw = '{"error":{"message":"' + escaped + '"}}'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text=raw))) as client:
        result = api.run_plan(sealed, tmp_path/'run', approval=approval(sealed), client=client)
    assert result['completed_calls'] == 1 and result['usage_cost_estimate_usd'] is None
    artifact = json.loads((tmp_path/'run/calls/001/raw-response.json').read_text(encoding="utf-8"))
    assert 'sk-secret-never-log' not in json.loads(artifact['body'])['error']['message']
    assert artifact['credential_echo_redaction'] is True


def test_private_output_boundary(api, tmp_path):
    with pytest.raises(ValueError, match='work/'):
        api.run_plan(plan(api), tmp_path.parent/'unsafe-run', mock=True)


def test_all_conditions_share_injection_boundary_instructions(api):
    calls = verify(plan(api))['calls']
    instructions = {call['payload'].get('instructions') for call in calls}
    assert len(instructions) == 1 and None not in instructions
    assert 'untrusted' in instructions.pop()


def test_windows_evidence_write_skips_directory_handle_but_fsyncs_file(api, tmp_path, monkeypatch):
    opened = []
    original = api.os.open
    def windows_open(path, flags, *args, **kwargs):
        opened.append(path)
        if Path(path).is_dir():
            raise PermissionError('Windows directory handle')
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(api, '_directory_fsync_supported', lambda: False, raising=False)
    monkeypatch.setattr(api.os, 'open', windows_open)
    api._write(tmp_path/'receipt.json', {'ok': True})
    assert json.loads((tmp_path/'receipt.json').read_text(encoding="utf-8")) == {'ok': True}
    assert len(opened) == 1


def test_unexpected_provider_exception_is_durable_and_never_exposes_secret(api, tmp_path):
    sealed = plan(api)
    def handler(request):
        raise RuntimeError('provider adapter leaked sk-secret-never-log')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.run_plan(sealed, tmp_path/'run', approval=approval(sealed), client=client)
    assert result['status'] == 'stopped' and result['completed_calls'] == 1
    assert result['reserved_cost_usd'] == .008 and result['usage_cost_estimate_usd'] is None
    evidence = ''.join(p.read_text(encoding="utf-8") for p in (tmp_path/'run').rglob('*.json'))
    assert 'sk-secret-never-log' not in evidence and 'provider adapter leaked' not in evidence
    outcome = json.loads((tmp_path/'run/calls/001/outcome.json').read_text(encoding="utf-8"))
    assert outcome['status'] == 'transport_error' and outcome['verdict'] is None


@pytest.mark.parametrize('interrupt', [KeyboardInterrupt, SystemExit])
def test_process_interrupt_propagates_with_durable_reservation(api, tmp_path, interrupt):
    sealed = plan(api)
    def handler(request):
        raise interrupt()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(interrupt):
            api.run_plan(sealed, tmp_path/'run', approval=approval(sealed), client=client)
    reservation = json.loads((tmp_path/'run/calls/001/reservation.json').read_text(encoding="utf-8"))
    assert reservation['reserved_cost_usd'] == .008
    assert (tmp_path/'run/calls/001/request.json').exists()
    with pytest.raises(ValueError, match='already|repeat|exist'):
        api.run_plan(sealed, tmp_path/'repeat', approval=approval(sealed))


def test_model_access_unexpected_exception_is_sanitized(api):
    def handler(request):
        raise RuntimeError('provider adapter leaked sk-secret-never-log')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.check_model_access('gpt-4.1-mini-2025-04-14', client=client)
    assert result['accessible'] is False and result['generation_calls'] == 0
    assert 'sk-secret-never-log' not in json.dumps(result)


@pytest.mark.parametrize('failed', [False, True])
def test_usage_cost_is_explicit_estimate_and_time_covers_failures(api, tmp_path, failed):
    from datetime import datetime
    sealed = plan(api); calls = iter(verify(sealed)['calls'])
    def handler(request):
        if failed:
            raise httpx.ReadTimeout('timed out', request=request)
        return httpx.Response(200, json=response(next(calls)))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = api.run_plan(sealed, tmp_path/'timed', approval=approval(sealed), client=client)
    assert result['latency_ms'] >= 0
    assert datetime.fromisoformat(result['ended_utc']) >= datetime.fromisoformat(result['started_utc'])
    assert result['actual_charge_usd'] is None
    assert result['usage_cost_estimate_usd'] == (None if failed else .00144)
    assert result['cost_basis'] == 'configured_snapshot_usage_estimate_not_provider_billing'
    assert 'actual_cost_usd' not in result
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path/'timed/calls').glob('*/outcome.json')]
    assert all(0 <= row['latency_ms'] <= result['latency_ms'] for row in rows)
    assert all(datetime.fromisoformat(row['ended_utc']) >= datetime.fromisoformat(row['started_utc']) for row in rows)
    assert all(row['actual_charge_usd'] is None for row in rows)
    assert all(row['usage_cost_estimate_usd'] == (None if failed else .00012) for row in rows)


def test_mock_reports_zero_charge_and_nonnegative_latency(api, tmp_path):
    result = api.run_plan(plan(api), tmp_path/'timed-mock', mock=True)
    assert result['actual_charge_usd'] == result['usage_cost_estimate_usd'] == 0
    assert result['latency_ms'] >= 0
