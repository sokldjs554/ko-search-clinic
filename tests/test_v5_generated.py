"""New generation path: offline HTTP fixtures, never live paid requests."""
import copy
import importlib
import json

import httpx
import pytest

from searchclinic.research_v5 import pipeline, transport
from test_v5_transport import bundle


@pytest.fixture
def generated(tmp_path, monkeypatch):
    assert importlib.util.find_spec('searchclinic.research_v5.generation'), 'generation transport missing'
    module = importlib.import_module('searchclinic.research_v5.generation')
    monkeypatch.setattr(transport, 'WORK_ROOT', tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-never-publish')
    return module


def test_parent_budget_and_query_only_context_reconstruction(generated):
    source = pipeline.freeze(bundle())
    study = generated.build_study(source)
    changed = bundle()
    changed['records'][0]['candidates'][0]['reasoning'] += ' do not use historical candidates'
    assert study == generated.build_study(pipeline.freeze(changed))
    body = pipeline.verify(study)
    assert body['max_calls'] == 38  # 2 + 2*3*3*2
    assert body['maximum_cost_usd'] == .3024
    assert body['analysis']['body']['phase'] == 'development'
    assert body['analysis']['body']['study_scope'] == 'full_system'
    assert all(not r['candidates'] for r in body['input']['body']['records'])
    plan = generated.build_generation_plan(study)
    assert len(plan['body']['calls']) == 2
    assert all(c['payload']['max_output_tokens'] == 1500 for c in plan['body']['calls'])
    assert generated.study_approval(study)['max_calls'] == 38


def test_empty_generation_still_produces_all_six_aligned_trials(generated, tmp_path):
    study = generated.build_study(pipeline.freeze(bundle()))
    result = generated.run_study(study, tmp_path/'empty', mock=True)
    assert result['provider_calls_executed'] == 0
    assert result['candidate_count'] == 0
    from searchclinic.research_v5.run_evidence import load_run
    candidates = json.loads((tmp_path/'empty/candidates.json').read_text(encoding='utf-8'))
    evidence = load_run(tmp_path/'empty/judges', candidates)
    assert len(evidence['body']['trials']) == 6
    assert all(t['verdicts'] == {'q1': [], 'q2': []} for t in evidence['body']['trials'])
    from searchclinic.research_v5.comparison import assemble_comparison
    protocol = json.loads((tmp_path/'empty/analysis.json').read_text(encoding='utf-8'))
    assembled = assemble_comparison(candidates,evidence['body']['trials'],protocol=protocol,transport_evidence=evidence)
    assert assembled['body']['generation_counts'] == {'q1':0,'q2':0}


def test_live_approval_rejected_before_any_provider_request(generated, tmp_path):
    study = generated.build_study(pipeline.freeze(bundle()))
    bad = generated.study_approval(study)
    bad['max_cost_usd'] += .01
    with pytest.raises(ValueError, match='approval'):
        generated.run_study(study, tmp_path/'bad', approval=bad)
    assert not (tmp_path/'bad').exists()


def test_generation_http_error_stops_before_judging_and_redacts_key(generated, tmp_path):
    study = generated.build_study(pipeline.freeze(bundle()))
    def handler(request):
        return httpx.Response(429, text='sk-never-publish')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = generated.run_study(study, tmp_path/'failed', approval=generated.study_approval(study), client=client)
    assert result['status'] == 'stopped_generation'
    assert result['provider_calls_executed'] == 1
    assert not (tmp_path/'failed/judges').exists()
    assert 'sk-never-publish' not in ''.join(p.read_text(encoding='utf-8') for p in (tmp_path/'failed').rglob('*.json'))
    with pytest.raises(ValueError, match='already|repeat|exist'):
        generated.run_study(study, tmp_path/'again', approval=generated.study_approval(study))


def test_generated_parser_preserves_valid_sibling_and_raw_indices(generated):
    study = generated.build_study(pipeline.freeze(bundle()))
    call = generated.build_generation_plan(study)['body']['calls'][0]
    query = call['context']['query']
    good = dict(target_query=query, diagnosis_family='spelling_variant', reasoning='Literal query token registered for this test.',
                user_words=[dict(form=query, tag='NNP', score=0.0)],synonym_groups=[],compound_expansions=[])
    bad = dict(good, target_query='wrong query')
    raw = dict(model=call['payload']['model'], status='completed',
               usage=dict(input_tokens=100,output_tokens=100,total_tokens=200),
               output=[dict(type='message',content=[dict(type='output_text',text=json.dumps({'candidates':[bad,good]}))])])
    outcome = generated.parse_generation(raw,call,call['payload']['model'])
    assert outcome['status'] == 'valid'
    assert outcome['verdict']['accepted_indices'] == [1]
    assert len(outcome['verdict']['candidates']) == 1
    assert outcome['verdict']['rejections'][0]['index'] == 0
    raw['model'] = 'different'
    assert generated.parse_generation(raw,call,call['payload']['model'])['verdict'] is None


def test_expanded_judge_profile_keeps_legacy_limit_and_supports_large_fixed_set():
    raw = bundle()
    raw['records'] = [copy.deepcopy(raw['records'][0]) for _ in range(16)]
    for i,r in enumerate(raw['records']):
        r['context']['query_id'] = f'q{i}'
        r['context']['observation']['query_id'] = f'q{i}'
    sealed = pipeline.freeze(raw)
    with pytest.raises(ValueError,match='fifteen'):
        transport.build_plan(sealed)
    assert 'profile' in __import__('inspect').signature(transport.build_plan).parameters, 'explicit new profile missing'
    plan = transport.build_plan(sealed,profile='generated-development-v5')
    assert plan['body']['call_count'] == 96
    assert transport._checked_plan(plan) == plan['body']


def test_generated_gate_requires_new_approval_only_commit(generated):
    assert hasattr(generated,'validate_approval_gate'), 'new approval gate missing'
    study = generated.build_study(pipeline.freeze(bundle()))
    parent = 'a'*40
    receipt = dict(approved_code_commit=parent,transport_approval=generated.study_approval(study))
    args = dict(study=study,approval=receipt,parent_commit=parent,
                changed_paths=['ops/v5-generated-approved.json'],
                commit_message='V5_GENERATED_APPROVED_PLAN='+study['sha256'],attempt='1')
    assert generated.validate_approval_gate(**args) == receipt['transport_approval']
    for change in ({'attempt':'2'},{'changed_paths':['ops/v5-approved.json']},
                   {'parent_commit':'b'*40},{'commit_message':'ordinary code update'}):
        with pytest.raises(ValueError,match='approval'):
            generated.validate_approval_gate(**dict(args,**change))


def test_real_transport_fixture_generation_to_judges_and_tamper_detection(generated,tmp_path):
    study = generated.build_study(pipeline.freeze(bundle()))
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        value = json.loads(payload['input'])
        if payload['text']['format']['name']=='retrieval_candidates':
            q = value['query']
            answer = {'candidates':[dict(target_query=q,diagnosis_family='spelling_variant',
                reasoning='Test fixture with a literal registered query token.',
                user_words=[dict(form=q,tag='NNP',score=0.0)],synonym_groups=[],compound_expansions=[])]}
        else:
            answer = {'assessments':[dict(patch_id=p['patch_id'],relation='uncertain',same_referent=None,
                scope_preserved=None,context_supported=None,confidence=0.,reasoning='Synthetic fixture only.',citations=[])
                for p in value['patches']]}
        return httpx.Response(200,json=dict(id='fixture',model=payload['model'],status='completed',
            usage=dict(input_tokens=100,output_tokens=100,total_tokens=200),
            output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(answer))])]))
    root = tmp_path/'pipeline'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = generated.run_study(study,root,approval=generated.study_approval(study),client=client)
    assert result['status']=='completed' and result['candidate_count']==2
    assert len(calls)==14
    recovered = generated.recover_candidates(study,root/'generation')
    assert recovered == json.loads((root/'candidates.json').read_text(encoding='utf-8'))
    from searchclinic.research_v5.run_evidence import load_run
    evidence = load_run(root/'judges',recovered,require_complete=True)
    assert len(evidence['body']['call_records'])==12
    outcome = root/'generation/calls/001/outcome.json'
    data = json.loads(outcome.read_text(encoding='utf-8'))
    data['verdict']['candidates']=[]
    outcome.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='disconnected'):
        generated.recover_candidates(study,root/'generation')


def test_all_rejected_generation_is_error_not_voluntary_abstention(generated,tmp_path):
    study = generated.build_study(pipeline.freeze(bundle()))
    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(200,json=dict(model=payload['model'],status='completed',
            usage=dict(input_tokens=100,output_tokens=100,total_tokens=200),
            output=[dict(type='message',content=[dict(type='output_text',text='{"candidates": [{}]}')])]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = generated.run_study(study,tmp_path/'rejected',approval=generated.study_approval(study),client=client)
    recovered = generated.recover_candidates(study,tmp_path/'rejected/generation')
    assert all(r['generation_error']=='all_candidates_rejected' for r in recovered['body']['records'])
    assert result['generation_diagnostics']['submitted_candidates']==2
    assert result['generation_diagnostics']['rejected_candidates']==2
    assert result['generation_diagnostics']['voluntary_abstention_queries']==0


def test_child_plan_bound_to_parent_even_when_both_studies_abstain(generated,tmp_path,monkeypatch):
    study = generated.build_study(pipeline.freeze(bundle()))
    first = generated.run_study(study,tmp_path/'first',mock=True)
    # An independently frozen generator limit changes the parent, while an
    # explicit empty response still yields exactly the same candidate bundle.
    monkeypatch.setattr(generated,'GEN_OUTPUT',1400)
    other = generated.build_study(pipeline.freeze(bundle()))
    assert other['sha256']!=study['sha256']
    second = generated.run_study(other,tmp_path/'second',mock=True)
    assert first['status']==second['status']=='completed'
    a=json.loads((tmp_path/'first/judges/plan.json').read_text(encoding='utf-8'))
    b=json.loads((tmp_path/'second/judges/plan.json').read_text(encoding='utf-8'))
    assert a['sha256']!=b['sha256']
