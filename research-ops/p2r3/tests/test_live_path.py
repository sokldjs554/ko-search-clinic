"""Original live provider path, with fake HTTP only; no paid requests or labels.

Actions must supply the official tokenizer cache before collecting execution
evidence. Local cache absence explicitly defers these tests, never substitutes
token counting or claims a full passing suite.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE_SHA = 'cd76f09cf647d1ee2691ed3fd3a217d4f4eb34de'
ORIGINAL_PLAN_HASH = '135f26a43bb9dd1c9f942a6b446fb637783af55e79ea29b82a3ae499bbb14b6b'
TOKENIZER_URL = 'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken'
TOKENIZER_SHA = '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
LOCAL_ORIGINAL = Path('/workspace/phase2-private/claude-handoff-20261014/original/p2r3-20261013')


def require_official_tokenizer_cache():
    cache_dir = os.environ.get('TIKTOKEN_CACHE_DIR', os.environ.get('DATA_GYM_CACHE_DIR', str(Path(tempfile.gettempdir()) / 'data-gym-cache')))
    cache = Path(cache_dir) / hashlib.sha1(TOKENIZER_URL.encode()).hexdigest()
    if not cache_dir or not cache.is_file():
        reason = 'Live-path execution deferred: official o200k_base cache required; no tokenizer replacement permitted'
        if os.environ.get('KSC_INPUT') or os.environ.get('GITHUB_ACTIONS') == 'true':
            pytest.fail(reason)
        pytest.skip(reason)
    assert hashlib.sha256(cache.read_bytes()).hexdigest() == TOKENIZER_SHA, 'Official tokenizer cache digest mismatch'


class FakeHTTP:
    def __init__(self, fault=None):
        self.fault = fault
        self.requests = []
        self.raw_bodies = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert request.full_url == 'https://api.openai.com/v1/chat/completions'
        assert request.get_method() == 'POST'
        assert request.get_header('Authorization') == 'Bearer fixture-live-path-only'
        assert timeout == 60
        if self.fault == 'timeout':
            raise TimeoutError('fixture private timeout detail')
        if self.fault in ('401', '429', '500'):
            raw = b'{"error":{"message":"fixture private response"}}'
            self.raw_bodies.append(raw)
            raise HTTPError(request.full_url, int(self.fault), 'fixture', {}, io.BytesIO(raw))
        body = {
            'model': 'gpt-4.1-mini-2025-04-14',
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10},
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{"candidates":[]}'}}],
        }
        if self.fault == 'missing_usage':
            del body['usage']
        elif self.fault == 'boolean_usage':
            body['usage']['prompt_tokens'] = True
        elif self.fault == 'negative_usage':
            body['usage']['prompt_tokens'] = -1
        elif self.fault == 'excess_input':
            body['usage']['prompt_tokens'] = 100000
        elif self.fault == 'excess_output':
            body['usage']['completion_tokens'] = 1501
        elif self.fault == 'model_substitution':
            body['model'] = 'unapproved-model'
        elif self.fault == 'finish_length':
            body['choices'][0]['finish_reason'] = 'length'
        elif self.fault == 'refusal':
            body['choices'][0]['message']['refusal'] = 'fixture refusal'
        elif self.fault == 'bad_candidates':
            body['choices'][0]['message']['content'] = '{"candidates":[{"target_query":"wrong fixture query"}]}'
        elif self.fault == 'multiple_choices':
            body['choices'].append(body['choices'][0].copy())
        raw = b'fixture invalid JSON' if self.fault == 'bad_json' else json.dumps(body).encode()
        self.raw_bodies.append(raw)
        response = io.BytesIO(raw)
        response.status = 200
        return response


@pytest.fixture
def live_fixture(tmp_path, monkeypatch):
    require_official_tokenizer_cache()
    if not os.environ.get('KSC_INPUT'):
        sys.path.insert(0, '/workspace/ko-search-clinic-gpt/src')
    from durable_transport import DurableTransport
    from searchclinic.research.phase2 import dev_comparison, provider
    from searchclinic.research.phase2.contracts import source_provenance
    original = Path(os.environ['KSC_INPUT']) / 'original' if os.environ.get('KSC_INPUT') else LOCAL_ORIGINAL
    original_plan = json.loads((original / 'execution-plan.json').read_text())
    assert original_plan['plan_hash'] == ORIGINAL_PLAN_HASH
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_PROTOCOL', 'artifacts/research/p2r3-20261013/protocol.json')
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_COMMIT', original_plan['body']['protocol_commit'])
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_PRIVATE_ROOT', str(tmp_path / 'private'))
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-live-path-only')
    assert source_provenance()['source_sha'] == SOURCE_SHA
    assert source_provenance()['source_dirty'] is False
    baseline = original / 'generation/rules-preparation.json'
    plan_path = tmp_path / 'test-plan.json'
    plan = dev_comparison.freeze_plan(baseline, plan_path)
    assert {k: v for k, v in plan['body'].items() if k != 'execution_root'} == {
        k: v for k, v in original_plan['body'].items() if k != 'execution_root'
    }
    selected = [q for q in plan['body']['requests'] if q['selected']]
    assert len(selected) == 7
    out = Path(plan['body']['execution_root']) / plan['plan_hash']
    approval = dict(approved=True, scope='development', plan_hash=plan['plan_hash'],
                    experiment_hash=plan['plan_hash'], config=provider.CONFIG,
                    request_hashes=[q['request_hash'] for q in selected],
                    execution_directory=str(out), approval_reference='OFFLINE_TEST_FIXTURE_ONLY')
    def run(fault=None, checkpoint_failure=False):
        http = FakeHTTP(fault)
        checkpoints = []
        def checkpoint():
            checkpoints.append(tuple(sorted(p.name for p in (tmp_path / 'transport').glob('*'))))
            if checkpoint_failure:
                raise RuntimeError('fixture checkpoint unavailable')
        transport = DurableTransport(tmp_path / 'transport', checkpoint, http.open)
        def transport_factory(*, network_authorized=False):
            assert network_authorized is True
            return transport
        monkeypatch.setattr(provider, 'OpenAIHTTPTransport', transport_factory)
        result = dev_comparison.run_plan(plan_path, baseline, approval=approval)
        return result, http, checkpoints
    return dict(run=run, out=out, tmp=tmp_path, plan=plan, plan_path=plan_path,
                baseline=baseline, selected=selected, approval=approval, module=dev_comparison)


def test_live_path_seals_all_ten_after_exactly_seven_and_refuses_restart(live_fixture):
    f = live_fixture
    result, http, checkpoints = f['run']()
    assert result['status'] == 'candidates_sealed'
    assert result['mode'] == 'live'
    assert result['actual_api_calls'] == result['confirmed_api_responses'] == result['transmission_attempts'] == len(http.requests) == 7
    assert len(checkpoints) == 14
    from searchclinic.research.splits import digest
    assert [digest(json.loads(r.data)) for r in http.requests] == [q['request_hash'] for q in f['selected']]
    for request in http.requests:
        payload = json.loads(request.data)
        assert payload['n'] == 1 and payload['max_completion_tokens'] == 1500
        assert payload['response_format'] == {'type': 'json_object'}
    bundle = json.loads((f['out'] / 'comparison-bundle.json').read_text())
    assert len(bundle['body']['contexts']) == 10
    assert len(bundle['body']['arms']['llm']) == len(bundle['body']['arms']['rules_plus']) == 10
    receipts = [json.loads(p.read_text()) for p in (f['out'] / 'receipts').glob('*.result.json')]
    assert len(receipts) == 7 and all(r['mode'] == 'live' and r['actual_api_calls'] == 1 for r in receipts)
    assert all(r['provider_usage'] == {'prompt_tokens': 100, 'completion_tokens': 10} for r in receipts)
    assert max(float(r['budget']['spent_usd']) for r in receipts) <= 0.15
    with pytest.raises(FileExistsError):
        f['module'].run_plan(f['plan_path'], f['baseline'], approval=f['approval'])
    assert len(http.requests) == 7


@pytest.mark.parametrize('fault', ['401', '429', '500', 'timeout', 'bad_json', 'missing_usage',
    'boolean_usage', 'negative_usage', 'excess_input', 'excess_output', 'model_substitution',
    'finish_length', 'refusal', 'bad_candidates', 'multiple_choices'])
def test_live_path_stops_first_fault_without_retry_or_evaluation(live_fixture, fault):
    f = live_fixture
    result, http, _ = f['run'](fault)
    assert result['status'] == 'stopped'
    assert result['performance_evaluation'] == 'not_permitted_for_incomplete_batch'
    assert len(http.requests) == result['transmission_attempts'] == 1
    assert not (f['out'] / 'comparison-bundle.json').exists()
    receipts = [json.loads(p.read_text()) for p in (f['out'] / 'receipts').glob('*.result.json')]
    assert len(receipts) == 1 and receipts[0]['status'] == 'error'
    assert receipts[0]['budget']['halted'] is True
    raw = [p.read_bytes() for p in (f['tmp'] / 'transport').glob('*.http-body.bin')]
    assert raw == http.raw_bodies
    if fault == 'timeout':
        assert result['actual_api_calls'] is None
        assert receipts[0]['billing_status'] == 'unknown_reserved'
    # An absent sentinel path proves incomplete batches fail before opening labels.
    with pytest.raises(ValueError, match='complete sealed batch'):
        f['module'].evaluate_run(f['plan_path'], f['baseline'], f['out'],
                                 f['tmp'] / 'NEVER_OPEN_LABELS', f['tmp'] / 'evaluation.json')
    assert len(http.requests) == 1


def test_live_path_checkpoint_failure_prevents_http_open(live_fixture):
    f = live_fixture
    result, http, checkpoints = f['run'](checkpoint_failure=True)
    assert result['status'] == 'stopped'
    assert http.requests == []
    assert len(checkpoints) == 1
    assert not (f['out'] / 'comparison-bundle.json').exists()
    assert not list((f['tmp'] / 'transport').glob('*.http-body.bin'))
