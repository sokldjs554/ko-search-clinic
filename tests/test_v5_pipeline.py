import copy
import json

import pytest

from searchclinic.research_v5 import pipeline
from searchclinic.research_v5.semantic import prepare_judge_request


def bundle():
    docs = [dict(doc_id='b', name='beta', description='catalog alias', category='sample'),
            dict(doc_id='d', name='delta', description='catalog alias', category='sample')]
    records = []
    for qid, query, term, doc in [('q1','alpha','beta',docs[0]),('q2','gamma','delta',docs[1])]:
        context = dict(query_id=qid, query=query, query_tokens=[query], search_total=0,
                       grep_total=0, similar=[], documents=[dict(doc_id=doc['doc_id'],
                       text=doc['name']+' '+doc['description'], tokens=[term])],
                       observation=dict(query_id=qid,query=query,split='dev',result_count=0))
        candidate = dict(target_query=query,diagnosis_family='synonym_gap',
                         reasoning='Source spelling alias candidate.',synonym_groups=[dict(terms=[query,term])])
        records.append(dict(context=context,candidates=[candidate],generation_error=None))
    return dict(version='v5',model_id='fixture-model',min_confidence=.8,seed=4,documents=docs,records=records)


def verdict(record, index=0):
    context, candidate = record['context'], record['candidates'][index]
    request = prepare_judge_request(context,candidate)
    doc = context['documents'][0]
    return dict(request_hash=request.request_hash,context_hash=request.context_hash,
                candidate_hash=request.candidate_hash,condition='rubric',protocol_id=request.protocol_id,
                model_id='fixture-model', assessments=[dict(patch_id='synonym:0',relation='equivalent',
                same_referent=True,scope_preserved=True,context_supported=True,confidence=.95,
                reasoning='Offline fixture only.',citations=[dict(doc_id=doc['doc_id'],quote=doc['text'],start=0,end=len(doc['text']))])])


def test_seal_roundtrip_is_detached_and_detects_tampering():
    raw=bundle()
    sealed=pipeline.freeze(raw)
    raw['model_id']='changed'
    assert pipeline.verify(sealed)['model_id']=='fixture-model'
    restored=pipeline.verify(sealed)
    restored['model_id']='changed'
    assert pipeline.verify(sealed)['model_id']=='fixture-model'
    sealed['body']['model_id']='tampered'
    with pytest.raises(ValueError):
        pipeline.verify(sealed)


def test_application_has_full_coverage_independent_patches_and_base_unchanged():
    raw=bundle()
    original=copy.deepcopy(raw)
    verdicts={r['context']['query_id']:[verdict(r)] for r in raw['records']}
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),verdicts))
    assert result['baseline_rankings']=={'q1':[],'q2':[]}
    assert result['rankings']=={'q1':['b'],'q2':['d']}
    assert all(d['candidate_index']==0 for d in result['decisions'].values())
    assert raw==original
    raw['records'].reverse()
    reversed_result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),verdicts))
    assert reversed_result['rankings']==result['rankings']
    assert result['runtime']['source_hash'] and result['runtime']['analyzer_hash']
    assert result['input_hash']==pipeline.freeze(original)['sha256']
    json.dumps(result,allow_nan=False)


def test_invalid_first_candidate_does_not_hide_valid_sibling_and_indices_preserved():
    raw=bundle()
    rec=raw['records'][0]
    invalid=copy.deepcopy(rec['candidates'][0])
    invalid['target_query']='switched target'
    rec['candidates'].insert(0,invalid)
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),{'q1':[], 'q2':[]},policy='first_valid'))
    assert result['decisions']['q1']['candidate_index']==1
    assert result['decisions']['q1']['candidate_decisions'][0]['errors']
    assert result['rankings']['q1']==['b']
    diagnostic=pipeline.verify(pipeline.diagnostic_candidates(pipeline.freeze(raw)))
    assert diagnostic['rankings']['q1']=={'1':['b']}
    assert diagnostic['errors']['q1']['0']


def test_empty_verdicts_hold_and_missing_coverage_is_error():
    sealed=pipeline.freeze(bundle())
    result=pipeline.verify(pipeline.apply_candidates(sealed,{'q1':[],'q2':[]}))
    assert result['rankings']==result['baseline_rankings']
    assert result['decisions']['q1']['candidate_index'] is None
    with pytest.raises(ValueError):
        pipeline.apply_candidates(sealed,{'q1':[]})


@pytest.mark.parametrize('change',['qrels','document','context_text','duplicate_record','nested_qrels'])
def test_manifest_rejects_leaks_unknown_evidence_and_duplicates(change):
    raw=bundle()
    if change=='qrels': raw['qrels']={'q1':{'b':1}}
    if change=='document': raw['records'][0]['context']['documents'][0]['doc_id']='missing'
    if change=='context_text': raw['records'][0]['context']['documents'][0]['text']='forged'
    if change=='duplicate_record': raw['records'].append(copy.deepcopy(raw['records'][0]))
    if change=='nested_qrels': raw['records'][0]['context']['observation']['qrels']={'b':1}
    with pytest.raises(ValueError):
        pipeline.apply_candidates(pipeline.freeze(raw),{'q1':[],'q2':[]})


def test_wrong_model_verdict_is_held_even_if_semantic_fields_pass():
    raw=bundle()
    v=verdict(raw['records'][0])
    v['model_id']='unfrozen-model'
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),{'q1':[v],'q2':[]}))
    assert result['decisions']['q1']['candidate_index'] is None
    assert 'model_id_mismatch' in result['decisions']['q1']['candidate_decisions'][0]['errors']


def test_score_requires_complete_frozen_application_and_retains_input_binding():
    sealed=pipeline.freeze(bundle())
    applied=pipeline.apply_candidates(sealed,{'q1':[],'q2':[]})
    queries=[dict(query_id=q,stratum='failure',concept_id=q) for q in ('q1','q2')]
    result=pipeline.verify(pipeline.score_application(applied,queries,{'q1':{'b':1},'q2':{'d':1}},bootstrap_samples=10))
    assert result['application_hash']==applied['sha256']
    assert result['scores']['summaries']['selected']['overall']['ndcg10']==0


def test_semantic_valid_sibling_keeps_original_index_after_literal_failure():
    raw=bundle()
    record=raw['records'][0]
    invalid=copy.deepcopy(record['candidates'][0])
    invalid['synonym_groups'][0]['terms'].append('invented-no-source')
    record['candidates'].insert(0,invalid)
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),
                           {'q1':[None,verdict(record,index=1)],'q2':[]}))
    assert result['decisions']['q1']['candidate_index']==1
    assert 'literal evidence' in result['decisions']['q1']['candidate_decisions'][0]['errors'][0]
    assert result['rankings']['q1']==['b']


def test_generation_failure_retains_query_and_held_baseline():
    raw=bundle()
    raw['records'][0].update(candidates=[],generation_error='offline generator failed')
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),{'q1':[],'q2':[]}))
    assert set(result['rankings'])=={'q1','q2'}
    assert result['decisions']['q1']['generation_error']=='offline generator failed'
    assert result['decisions']['q1']['status']=='held'


def test_importing_pipeline_does_not_import_labels_or_evaluators():
    import subprocess
    import sys
    code = """
import sys
from searchclinic.research_v5 import pipeline
for name in sys.modules:
    assert not name.startswith('searchclinic.evaluation'), name
    assert name != 'searchclinic.corpus.evalset', name
    assert name != 'searchclinic.research_v5.evaluation', name
"""
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0, result.stderr


@pytest.mark.parametrize('policy',['semantic','first_valid'])
def test_generation_error_prohibits_applying_existing_candidates(policy):
    raw=bundle()
    raw['records'][0]['generation_error']='incomplete generator response'
    result=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(raw),
        {'q1':[verdict(raw['records'][0])],'q2':[]},policy=policy))
    assert result['rankings']['q1']==result['baseline_rankings']['q1']
    assert result['decisions']['q1']['status']=='held'
    assert result['decisions']['q1']['candidate_index'] is None
    assert 'generation_error' in result['decisions']['q1']['candidate_decisions'][0]['errors']


def test_scoring_rejects_extra_labels_and_changed_implementation_identity():
    applied=pipeline.apply_candidates(pipeline.freeze(bundle()),{'q1':[],'q2':[]})
    queries=[dict(query_id=q,stratum='failure',concept_id=q) for q in ('q1','q2')]
    qrels={'q1':{'b':1},'q2':{'d':1}}
    body=pipeline.verify(applied)
    body['qrels']=qrels
    with pytest.raises(ValueError):
        pipeline.score_application(pipeline.freeze(body),queries,qrels,bootstrap_samples=10)
    body=pipeline.verify(applied)
    body['runtime']['source_hash']='0'*64
    with pytest.raises(ValueError):
        pipeline.score_application(pipeline.freeze(body),queries,qrels,bootstrap_samples=10)
    body=pipeline.verify(applied)
    body['rankings']['extra']=[]
    with pytest.raises(ValueError):
        pipeline.score_application(pipeline.freeze(body),queries,qrels,bootstrap_samples=10)


def test_runtime_hash_manifest_does_not_read_evaluator_or_label_sources():
    applied=pipeline.verify(pipeline.apply_candidates(pipeline.freeze(bundle()),{'q1':[],'q2':[]}))
    files=applied['runtime']['source_files']
    assert 'research_v5/pipeline.py' in files
    assert 'research_v5/semantic.py' in files
    assert not any('evaluation' in name or 'evalset' in name for name in files)


def test_lazy_package_exports_preserve_public_object_identity():
    from importlib import import_module
    import searchclinic.corpus as corpus
    import searchclinic.patch as patch
    for package, routes in [(corpus, {'catalog': {'Document','CATALOG','load_catalog'}}),
                            (patch, {'ir': {'Prescription','PATCH_KINDS'},
                                     'es_render': {'to_es_settings','render_es_json'}})]:
        default='evalset' if package is corpus else 'gate'
        for name in package.__all__:
            module=next((module for module,names in routes.items() if name in names),default)
            assert getattr(package,name) is getattr(import_module(f'{package.__name__}.{module}'),name)


def test_scoring_rejects_extra_label_fields_inside_decisions():
    applied=pipeline.apply_candidates(pipeline.freeze(bundle()),{'q1':[],'q2':[]})
    body=pipeline.verify(applied)
    body['decisions']['q1']['qrels']={'b':1}
    queries=[dict(query_id=q,stratum='failure',concept_id=q) for q in ('q1','q2')]
    with pytest.raises(ValueError):
        pipeline.score_application(pipeline.freeze(body),queries,{'q1':{'b':1},'q2':{'d':1}},bootstrap_samples=10)


def test_diagnostic_preserves_generator_failure_with_no_candidates():
    raw=bundle()
    raw['records'][0].update(candidates=[],generation_error='empty malformed generator output')
    result=pipeline.verify(pipeline.diagnostic_candidates(pipeline.freeze(raw)))
    assert result['rankings']['q1']=={}
    assert result['generation_errors']=={'q1':'empty malformed generator output','q2':None}
    assert result['statuses']=={'q1':'generation_error','q2':'candidates_replayed'}


def test_diagnostic_generator_failure_cannot_replay_present_candidates():
    raw=bundle()
    raw['records'][0]['generation_error']='partial generator response'
    raw['records'][1]['candidates']=[]
    result=pipeline.verify(pipeline.diagnostic_candidates(pipeline.freeze(raw)))
    assert result['rankings']['q1']=={}
    assert result['errors']['q1']=={'0':'generation_error'}
    assert result['generation_errors']['q1']=='partial generator response'
    assert result['statuses']=={'q1':'generation_error','q2':'abstained'}
