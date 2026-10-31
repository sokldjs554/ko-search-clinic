"""Offline synthetic cases exercising the evaluator; not research scores."""
import copy
import hashlib
import importlib
import json
from dataclasses import asdict

import pytest

from searchclinic.corpus.catalog import Document
from searchclinic.index.engine import SearchEngine
from searchclinic.research.costs import CostRecord
from searchclinic.research.splits import digest


def api():
    return importlib.import_module('searchclinic.research.phase2.generation')


def evaluator():
    assert importlib.util.find_spec('searchclinic.research.phase2.evaluator'), 'evaluator missing'
    return importlib.import_module('searchclinic.research.phase2.evaluator')


@pytest.fixture
def prepared(tmp_path):
    g=api()
    docs=[Document('S1','수문','강의 물을 조절하는 시설','fixture'),
          Document('S2','환기','공기의 흐름을 바꾸는 시설','fixture')]
    engine=SearchEngine(docs)
    contexts=[g.build_context(engine,'synthetic-f','수믄'),g.build_context(engine,'synthetic-h','수문')]
    rx=dict(target_query='수믄',diagnosis_family='spelling_variant',
            reasoning='단위 시험의 수문 표기 변형을 연결합니다.',
            synonym_groups=[{'terms':['수문','수믄']}])
    # Fixture records exercise equal-input plumbing, not a claim that an LLM ran.
    rules=[g.generate_rules(c) for c in contexts]
    llm=copy.deepcopy(rules)
    for c,r in zip(contexts,llm):
        r.update(arm='llm',model='offline-synthetic-fixture',error=None,
                 costs=asdict(CostRecord(model_calls=0,latency_ms=0)))
        r['candidates']=g.validate_candidates(c,[rx]) if c.query_id=='synthetic-f' else []
    labels={'review_status':'independent_review_complete', 'synthetic':True,
            'queries':[{'query_id':'synthetic-f','query':'수믄','qrels':{'S1':2},'stratum':'challenge','group_id':'water'},
                       {'query_id':'synthetic-h','query':'수문','qrels':{'S1':2},'stratum':'healthy','group_id':'water'}]}
    path=tmp_path/'private-labels.json'
    path.write_text(json.dumps(labels,ensure_ascii=False),encoding='utf-8')
    commitment=hashlib.sha256(path.read_bytes()).hexdigest()
    bundle=g.seal_bundle(contexts,{'rules_plus':rules,'llm':llm},[asdict(d) for d in docs],digest([asdict(d) for d in docs]),commitment)
    g.write_once(tmp_path/'public-input-manifest.json', g.public_input_manifest(bundle))
    return bundle,path


def refresh_fixture_manifest(sealed,path):
    """A new synthetic fixture input, not modification of a research artifact."""
    g=api()
    sealed['body']['input_hash']=digest({'contexts':sealed['body']['contexts'],'documents':sealed['body']['documents']})
    sealed['seal_hash']=digest(sealed['body'])
    (path.parent/'public-input-manifest.json').write_text(json.dumps(g.public_input_manifest(sealed)),encoding='utf-8')


def test_full_gate_accepts_without_feedback_to_generator(prepared):
    sealed,path=prepared
    before=copy.deepcopy(sealed)
    result=evaluator().evaluate_bundle(sealed,path,synthetic_only=True)
    assert sealed==before
    assert result['synthetic_only']
    assert result['arms']['llm']['queries'][0]['accepted']
    assert result['arms']['llm']['queries'][0]['after']['ndcg']==1
    assert result['arms']['llm']['healthy_regressions']==0
    assert len(result['arms']['llm']['ledger'])==1
    assert result['comparison']['superiority_claim'] is False
    assert result['arms']['llm']['costs']['search_calls']>0


def test_rules_only_cannot_open_final_labels(prepared):
    sealed,path=prepared
    del sealed['body']['arms']['llm']
    sealed['seal_hash']=digest(sealed['body'])
    # Missing file verifies preflight happens before attempting label access.
    with pytest.raises(ValueError,match='both'):
        evaluator().evaluate_bundle(sealed,path.with_name('unavailable.json'))


def test_partial_label_coverage_rejected(prepared):
    sealed,path=prepared
    labels=json.loads(path.read_text(encoding='utf-8'))
    labels['queries'].pop()
    path.write_text(json.dumps(labels),encoding='utf-8')
    sealed['body']['label_commitment']=hashlib.sha256(path.read_bytes()).hexdigest()
    sealed['seal_hash']=digest(sealed['body'])
    refresh_fixture_manifest(sealed,path)
    with pytest.raises(ValueError,match='coverage'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


def test_labels_changed_after_candidates_rejected(prepared):
    sealed,path=prepared
    path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='label commitment'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


def test_unreviewed_or_nonsynthetic_fixture_evaluation_blocked(prepared):
    sealed,path=prepared
    with pytest.raises(ValueError,match='synthetic'):
        evaluator().evaluate_bundle(sealed,path)
    labels=json.loads(path.read_text(encoding='utf-8'))
    labels['review_status']='pending'
    path.write_text(json.dumps(labels),encoding='utf-8')
    sealed['body']['label_commitment']=hashlib.sha256(path.read_bytes()).hexdigest()
    sealed['seal_hash']=digest(sealed['body'])
    refresh_fixture_manifest(sealed,path)
    with pytest.raises(ValueError,match='review'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


def test_unsupported_patch_preserved_as_rejection(prepared):
    sealed,path=prepared
    c=importlib.import_module('searchclinic.research.phase2.contracts').Context.model_validate(sealed['body']['contexts'][0])
    badrx=dict(target_query='수믄',diagnosis_family='synonym_gap',reasoning='정답과 무관한 연결을 거부하는 단위 시험입니다.',
               synonym_groups=[{'terms':['환기','수믄']}])
    # Include the second document as context evidence so the gate, not the literal guard, rejects it.
    c=c.model_copy(update={'documents':c.documents+[importlib.import_module('searchclinic.research.phase2.contracts').PublicDocument(
        doc_id='S2',text='환기 공기의 흐름을 바꾸는 시설',tokens=['환기'])]}) if all(d.doc_id!='S2' for d in c.documents) else c
    sealed['body']['contexts'][0]=c.model_dump()
    for arm in ('llm','rules_plus'):
        sealed['body']['arms'][arm][0]['context_hash']=digest(c.model_dump())
    sealed['body']['arms']['llm'][0]['candidates']=api().validate_candidates(c,[badrx])
    sealed['seal_hash']=digest(sealed['body'])
    refresh_fixture_manifest(sealed,path)
    result=evaluator().evaluate_bundle(sealed,path,synthetic_only=True)
    q=result['arms']['llm']['queries'][0]
    assert q['accepted'] is False and q['submissions']==1
    assert q['trace'][0]['reason']=='rejected'
    assert result['arms']['llm']['ledger']==[]


def test_unknown_qrel_documents_rejected(prepared):
    sealed,path=prepared
    labels=json.loads(path.read_text(encoding='utf-8'))
    labels['queries'][0]['qrels']={'NOT_IN_CORPUS':2}
    path.write_text(json.dumps(labels),encoding='utf-8')
    sealed['body']['label_commitment']=hashlib.sha256(path.read_bytes()).hexdigest()
    sealed['seal_hash']=digest(sealed['body'])
    refresh_fixture_manifest(sealed,path)
    with pytest.raises(ValueError,match='qrel'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


def test_reseal_does_not_hide_forged_evidence(prepared):
    sealed,path=prepared
    sealed['body']['arms']['llm'][0]['candidates'][0]['evidence'][0]['text']='위조'
    sealed['seal_hash']=digest(sealed['body'])
    with pytest.raises(ValueError,match='evidence'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


def test_request_contains_same_context_and_no_qrels(prepared):
    g=api()
    sealed,_=prepared
    c=importlib.import_module('searchclinic.research.phase2.contracts').Context.model_validate(sealed['body']['contexts'][0])
    assert hasattr(g,'build_llm_request'), 'one shot request missing'
    req=g.build_llm_request(c)
    assert req['context']==c.model_dump()
    assert req['max_output_tokens']==1500
    assert req['automatic_retries']==0
    assert 'qrels' not in json.dumps(req)


def test_added_document_cannot_retain_dataset_identity(prepared):
    sealed,path=prepared
    sealed['body']['documents'].append({'doc_id':'EXTRA','name':'수문','description':'강의 물을 조절하는 시설','category':'fixture'})
    sealed['seal_hash']=digest(sealed['body'])
    with pytest.raises(ValueError,match='input'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


@pytest.mark.parametrize('field,value',[('source_sha','not-a-commit'),('protocol_commit','wrong-freeze'),('source_dirty','flip')])
def test_falsified_provenance_rejected(prepared,field,value):
    sealed,path=prepared
    sealed['body'][field]=not sealed['body'][field] if value=='flip' else value
    sealed['seal_hash']=digest(sealed['body'])
    with pytest.raises(ValueError,match='provenance'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)


@pytest.mark.parametrize('location',['body','record'])
def test_unknown_label_or_feedback_fields_rejected(prepared,location):
    sealed,path=prepared
    if location=='body':
        sealed['body']['qrels']={'leaked-label':3}
    else:
        sealed['body']['arms']['llm'][0]['feedback']='post-evaluation feedback'
    sealed['seal_hash']=digest(sealed['body'])
    with pytest.raises(ValueError,match='fields'):
        evaluator().evaluate_bundle(sealed,path,synthetic_only=True)
