"""Offline posthoc-development continuation; real provider path, fake HTTP."""
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, '/workspace/ko-search-clinic-gpt/src')

@pytest.fixture
def setup(tmp_path, monkeypatch):
    module = importlib.import_module('continuation')
    root = Path(__file__).resolve().parents[1]
    parent = Path(os.environ.get('KSC_PARENT_ROOT', root / 'received-38508730307'))
    original = Path(os.environ.get('KSC_INPUT', '/workspace/phase2-private/claude-handoff-20261014'))
    original = original / 'original/p2r3-20261013' if not os.environ.get('KSC_INPUT') else original / 'original'
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_PROTOCOL', 'artifacts/research/p2r3-20261013/protocol.json')
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_COMMIT', '47e2085ce04c715e738ff8330b559f398dad9d3a')
    monkeypatch.setenv('SEARCHCLINIC_PHASE2_PRIVATE_ROOT', str(tmp_path/'private'))
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR', str(parent/'official-tokenizer-cache'))
    monkeypatch.setenv('OPENAI_API_KEY','fixture-continuation-only')
    monkeypatch.setenv('KSC_CONTINUATION_TEST_RAW',str(tmp_path/'run/raw-http'))
    # A fixture digest binds this test package; it is not a real signed artifact.
    artifact=Path(os.environ.get('KSC_PARENT_ARTIFACT','/workspace/attachments/343e5e33-b261-47fb-96da-c19212f169fb/p2r3-encrypted-run-38508730307.zip'))
    amendment=tmp_path/'amendment.json'
    args=(original/'execution-plan.json',parent,artifact,original/'generation/rules-preparation.json')
    frozen=module.freeze_amendment(*args,amendment,approval_reference='OFFLINE_CONTINUATION_FIXTURE')
    return module,args,amendment,frozen,tmp_path


def fake_provider(monkeypatch, fault=None):
    from searchclinic.research.phase2 import provider
    calls=[]
    class FakeTransport:
        def __init__(self, *, network_authorized=False):assert network_authorized is True
        def __call__(self,payload,*,on_event):
            from durable_transport import DurableTransport
            content='{"candidates":[]}'
            if fault=='candidate':content='{"candidates":[{"target_query":"wrong-fixture-target"}]}'
            usage={'prompt_tokens':100,'completion_tokens':10}
            if fault=='usage':usage['prompt_tokens']=True
            response={'model':provider.MODEL,'usage':usage,
                      'choices':[{'finish_reason':'length' if fault=='length' else 'stop','message':{'content':content}}]}
            def open_http(request,timeout):
                calls.append(json.loads(request.data))
                if fault=='timeout':raise TimeoutError('fixture')
                raw=io.BytesIO(json.dumps(response).encode());raw.status=200
                return raw
            return DurableTransport(Path(os.environ['KSC_CONTINUATION_TEST_RAW']),lambda:None,open_http)(payload,on_event=on_event)
    monkeypatch.setattr(provider,'OpenAIHTTPTransport',FakeTransport)
    return calls


def test_freeze_carries_one_known_parent_and_exact_remaining_six(setup):
    module,args,path,amendment,tmp=setup
    body=amendment['body']
    assert body['parent']['actual_calls']==1
    assert body['parent']['spent_usd']=='0.0018768'
    assert len(body['original_request_hashes'])==7
    assert body['remaining_request_hashes']==body['original_request_hashes'][1:]
    assert body['parent']['request_hash'] not in body['remaining_request_hashes']
    assert body['posthoc_development_amendment'] is True
    assert body['family'].endswith('-continuation-1')
    assert module.verify_amendment(path,*args)==amendment


def test_six_calls_then_seal_all_ten_without_repairing_parent(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    calls=fake_provider(monkeypatch);claims=[];checkpoints=[]
    result=module.run_continuation(path,*args,tmp/'run',claim_callback=claims.append,checkpoint=lambda:checkpoints.append(True))
    assert result['status']=='candidates_sealed'
    assert len(calls)==6 and len(claims)==1
    assert result['aggregate']['calls']==7
    assert float(result['aggregate']['spent_usd'])<0.15
    bundle=json.loads((tmp/'run/comparison-bundle.json').read_text())
    records=bundle['body']['arms']['llm']
    assert len(records)==10
    errors=[r for r in records if r['error']]
    assert len(errors)==1 and errors[0]['candidates']==[]
    assert errors[0]['error']['type']=='PosthocCandidateValidationFailure'
    assert module.verify_completed_run(path,*args,tmp/'run')[1]==bundle
    from searchclinic.research.splits import digest
    assert [digest(p) for p in calls]==amendment['body']['remaining_request_hashes']
    with pytest.raises(FileExistsError):
        module.run_continuation(path,*args,tmp/'run',claim_callback=claims.append,checkpoint=lambda:None)
    assert len(calls)==6


def test_known_candidate_errors_do_not_retry_or_exceed_original_seven(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    calls=fake_provider(monkeypatch,'candidate')
    result=module.run_continuation(path,*args,tmp/'run',claim_callback=lambda f:None,checkpoint=lambda:None)
    assert result['status']=='candidates_sealed' and len(calls)==6
    assert result['aggregate']['calls']==7 and result['aggregate']['halted'] is False
    bundle=json.loads((tmp/'run/comparison-bundle.json').read_text())
    assert sum(bool(r['error']) for r in bundle['body']['arms']['llm'])==7


@pytest.mark.parametrize('fault',['timeout','usage','length'])
def test_fatal_transport_usage_or_incomplete_response_stops(setup,monkeypatch,fault):
    module,args,path,amendment,tmp=setup
    calls=fake_provider(monkeypatch,fault)
    result=module.run_continuation(path,*args,tmp/'run',claim_callback=lambda f:None,checkpoint=lambda:None)
    assert result['status']=='stopped' and len(calls)==1
    assert result['aggregate']['halted'] is True
    assert not (tmp/'run/comparison-bundle.json').exists()


def test_checkpoint_and_claim_failures_prevent_any_new_request(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    calls=fake_provider(monkeypatch)
    def fail(*a):raise RuntimeError('fixture unavailable')
    with pytest.raises(RuntimeError):
        module.run_continuation(path,*args,tmp/'claim-fail',claim_callback=fail,checkpoint=lambda:None)
    with pytest.raises(RuntimeError):
        module.run_continuation(path,*args,tmp/'checkpoint-fail',claim_callback=lambda f:None,checkpoint=fail)
    assert calls==[]


def test_changed_amendment_or_parent_receipt_blocks_before_claim(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    calls=fake_provider(monkeypatch);claims=[]
    amendment['body']['remaining_request_hashes'].append(amendment['body']['parent']['request_hash'])
    path.write_text(json.dumps(amendment))
    with pytest.raises(ValueError):
        module.run_continuation(path,*args,tmp/'run',claim_callback=claims.append,checkpoint=lambda:None)
    assert not claims and not calls


def test_evaluator_rejects_tampered_raw_before_opening_any_labels(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    fake_provider(monkeypatch)
    module.run_continuation(path,*args,tmp/'run',claim_callback=lambda f:None,checkpoint=lambda:None)
    raw=next((tmp/'run/raw-http').glob('*.http-body.bin'))
    raw.write_bytes(b'tampered fixture')
    with pytest.raises(ValueError):
        module.evaluate_continuation(path,*args,tmp/'run',tmp/'LABELS_MUST_NOT_OPEN',tmp/'evaluation.json')
    assert not (tmp/'evaluation.json').exists()


def test_evaluator_rejects_incomplete_batch_before_labels(setup,monkeypatch):
    module,args,path,amendment,tmp=setup
    fake_provider(monkeypatch,'timeout')
    module.run_continuation(path,*args,tmp/'run',claim_callback=lambda f:None,checkpoint=lambda:None)
    with pytest.raises(ValueError):
        module.evaluate_continuation(path,*args,tmp/'run',tmp/'LABELS_MUST_NOT_OPEN',tmp/'evaluation.json')
