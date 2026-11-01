"""Label-free empty-result selection is post-hoc development, not a final result."""
import importlib


def choose(baseline, rankings, decision):
    return importlib.import_module('searchclinic.research_v5.retrieval_aware').choose(baseline,rankings,decision)


def decisions(selected=0):
    return {'candidate_index':selected,'candidate_decisions':[
        {'candidate_index':0,'eligible':True,'confidence':.99},
        {'candidate_index':1,'eligible':True,'confidence':.85}]}


def test_empty_result_does_not_outrank_nonempty_result_by_semantic_confidence():
    assert choose([],{'0':[],'1':['document']},decisions())==1


def test_nonempty_baseline_keeps_original_selection():
    assert choose(['original'],{'0':['original'],'1':['new']},decisions())==0


def test_never_promotes_semantically_rejected_candidate():
    d=decisions();d['candidate_decisions'][1]['eligible']=False
    assert choose([],{'0':[],'1':['document']},d) is None


def test_no_nonempty_eligible_option_abstains_and_ties_keep_original_index():
    assert choose([],{'0':[],'1':[]},decisions()) is None
    d=decisions();d['candidate_decisions'][1]['confidence']=.99
    assert choose([],{'0':['a'],'1':['b']},d)==0


def test_sealed_selection_is_label_free_and_does_not_mutate_source():
    import copy
    from test_v5_comparison import inputs,trials_for
    from searchclinic.research_v5 import comparison,retrieval_aware
    bundle,queries,qrels=inputs()
    source=comparison.assemble_comparison(bundle,trials_for(bundle),protocol=
        comparison.freeze_analysis_protocol(bundle,candidate_source='mock'))
    original=copy.deepcopy(source)
    selected=retrieval_aware.assemble(source)
    assert source==original
    report=retrieval_aware.score(selected,queries,qrels)
    assert report['stage']=='posthoc_development_only_not_primary'
    assert report['additional_provider_calls']==0 and report['superiority_claim'] is False
    assert report['arms']['pair:1']['apply_count']==2
    assert report['scores']['summaries']['pair:1']['overall']['ndcg10']==1


def test_resigned_changed_selection_is_rejected_by_source_binding():
    import pytest
    from test_v5_comparison import inputs,trials_for
    from searchclinic.research_v5 import comparison,retrieval_aware,pipeline
    bundle,queries,qrels=inputs()
    source=comparison.assemble_comparison(bundle,trials_for(bundle),protocol=
        comparison.freeze_analysis_protocol(bundle,candidate_source='mock'))
    selection=retrieval_aware.assemble(source)
    selection['body']['arms']['pair:1']['rankings']['q1']=[]
    with pytest.raises(ValueError,match='binding'):
        retrieval_aware.score(pipeline.freeze(selection['body']),queries,qrels)


def test_empty_candidates_held_status_matches_selection():
    from test_v5_comparison import inputs,trials_for
    from searchclinic.research_v5 import comparison,retrieval_aware,pipeline
    bundle,_,_=inputs()
    source=comparison.assemble_comparison(bundle,trials_for(bundle),protocol=
        comparison.freeze_analysis_protocol(bundle,candidate_source='mock'))
    source['body']['diagnostic']['body']['rankings']['q1']={'0':[]}
    source['body']['diagnostic']=pipeline.freeze(source['body']['diagnostic']['body'])
    out=retrieval_aware.assemble(pipeline.freeze(source['body']))
    decision=out['body']['arms']['pair:1']['decisions']['q1']
    assert decision['candidate_index'] is None and decision['status']=='held'
    assert out['body']['arms']['pair:1']['rankings']['q1']==[]
