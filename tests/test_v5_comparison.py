"""Frozen comparison orchestration; fixtures are not experimental evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from searchclinic.research_v5 import comparison, pipeline
from searchclinic.research_v5.semantic import prepare_judge_request


def inputs():
    docs = [dict(doc_id='b', name='beta', description='catalog alias', category='sample'),
            dict(doc_id='d', name='delta', description='catalog alias', category='sample')]
    records = []
    for qid, query, term, doc in [('q1', 'alpha', 'beta', docs[0]), ('q2', 'gamma', 'delta', docs[1])]:
        context = dict(query_id=qid, query=query, query_tokens=[query], search_total=0,
                       grep_total=0, similar=[], documents=[dict(doc_id=doc['doc_id'],
                       text=doc['name'] + ' ' + doc['description'], tokens=[term])],
                       observation=dict(query_id=qid, query=query, split='dev', result_count=0))
        candidate = dict(target_query=query, diagnosis_family='synonym_gap', reasoning='Synthetic fixture only.',
                         synonym_groups=[dict(terms=[query, term])])
        records.append(dict(context=context, candidates=[candidate], generation_error=None))
    bundle = pipeline.freeze(dict(version='v5', model_id='fixture-model', min_confidence=.8,
                                  seed=4, documents=docs, records=records))
    queries = [dict(query_id=q, stratum='failure', concept_id=q) for q in ('q1', 'q2')]
    return bundle, queries, {'q1': {'b': 1}, 'q2': {'d': 1}}


def trials_for(bundle, repeats=2):
    trials = []
    for condition in ('pair', 'context', 'rubric'):
        verdicts = {}
        for record in pipeline.verify(bundle)['records']:
            context = record['context']
            values = []
            for candidate in record['candidates']:
                try:
                    request = prepare_judge_request(context, candidate, condition)
                except ValueError:
                    values.append(None)
                    continue
                doc = context['documents'][0]
                values.append(dict(**{k: v for k, v in request.model_dump().items() if k != 'body'},
                    model_id='fixture-model', assessments=[dict(patch_id='synonym:0', relation='equivalent',
                    same_referent=True, scope_preserved=True, context_supported=None if condition == 'pair' else True,
                    confidence=.95, reasoning='Synthetic test only.', citations=[] if condition == 'pair' else
                    [dict(doc_id=doc['doc_id'], quote=doc['text'], start=0, end=len(doc['text']))])]))
            verdicts[context['query_id']] = values
        for repeat in range(1, repeats + 1):
            trials.append(dict(condition=condition, repeat=repeat, input_hash=bundle['sha256'],
                               verdicts=copy.deepcopy(verdicts)))
    return trials


def compare(bundle=None, trials=None, **kwargs):
    source, queries, qrels = inputs()
    bundle = bundle or source
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='mock', repeats=2)
    return comparison.compare_conditions(bundle, trials or trials_for(bundle), queries, qrels,
        protocol=protocol, bootstrap_samples=30, random_repeats=3, **kwargs)


def test_full_assembly_has_baselines_repeats_and_unknown_semantic_correctness():
    result = compare()
    assert result['study_scope'] == 'selection_only'
    assert result['superiority_claim'] is False
    assert {'no_repair', 'first_valid', 'rules_plus', 'pair:1', 'context:2', 'rubric:2'} <= set(result['scores']['summaries'])
    assert result['arms']['first_valid']['description'] != 'GPT-generated'
    assert result['arms']['rubric:1']['apply_count'] == 2
    assert result['arms']['rubric:1']['semantic_correctness']['status'] == 'UNKNOWN'
    assert result['arms']['rubric:1']['semantic_correctness']['correct_count'] is None
    assert result['paired_primary']['vs_no_repair']['ci_level'] == .975
    assert result['paired_primary']['vs_rules_plus']['ci_level'] == .975
    assert result['paired_primary']['vs_no_repair']['per_query']['q1']['ndcg10'] == 1
    assert result['repeat_variability']['rubric']['repeats'] == 2
    assert all(r['apply_count'] == 2 for r in result['matched_random']['rubric:1'])
    assert result['costs']['comparison_provider_calls'] == 0
    assert result['rules_plus']['context_policy'] == 'fresh_public_retrieval_context'
    assert result['threshold_diagnostic']['interpretation'] == 'diagnostic_only_not_optimal_threshold_or_probability'
    json.dumps(result, allow_nan=False)


def test_holds_count_oracle_useful_false_holds_and_malformed_separately():
    bundle, _, _ = inputs()
    trials = trials_for(bundle)
    trials[0]['verdicts']['q1'] = [{'invalid': 'verdict'}]
    trials[0]['verdicts']['q2'] = [None]
    result = compare(bundle, trials)
    arm = result['arms']['pair:1']
    assert arm['apply_count'] == 0 and arm['hold_count'] == 2
    assert arm['malformed_verdict_count'] == 1
    assert arm['missing_verdict_count'] == 1
    assert arm['useful_candidate_false_hold_count'] == 2
    assert arm['harmful_accepted_count'] == 0


@pytest.mark.parametrize('change', ['missing_trial', 'duplicate_trial', 'input_hash', 'missing_query', 'short_verdicts', 'extra_repeat'])
def test_rejects_incomplete_or_misaligned_comparison(change):
    bundle, _, _ = inputs()
    trials = trials_for(bundle)
    if change == 'missing_trial': trials.pop()
    if change == 'duplicate_trial': trials.append(copy.deepcopy(trials[0]))
    if change == 'input_hash': trials[0]['input_hash'] = '0' * 64
    if change == 'missing_query': trials[0]['verdicts'].pop('q1')
    if change == 'short_verdicts': trials[0]['verdicts']['q1'] = []
    if change == 'extra_repeat': trials[0]['repeat'] = 3
    with pytest.raises(ValueError):
        compare(bundle, trials)


def test_generation_missing_errors_and_invalid_candidates_remain_in_denominator():
    bundle, _, _ = inputs()
    body = pipeline.verify(bundle)
    body['records'][0].update(candidates=[], generation_error='missing output')
    body['records'][1]['candidates'][0]['target_query'] = 'wrong'
    changed = pipeline.freeze(body)
    result = compare(changed)
    arm = result['arms']['rubric:1']
    assert arm['hold_count'] == 2
    assert arm['generation_missing_count'] == 1
    assert arm['generation_error_count'] == 1
    assert arm['invalid_candidate_count'] == 1


def test_human_semantic_labels_are_separate_from_retrieval_success():
    labels = {'q1': {'0': False}, 'q2': {'0': True}}
    result = compare(human_semantics=labels)
    semantic = result['arms']['rubric:1']['semantic_correctness']
    assert semantic == dict(status='human_labeled', correct_count=1, incorrect_count=1, unknown_count=0)
    assert result['scores']['summaries']['rubric:1']['overall']['ndcg10'] == 1


def test_final_is_blocked_without_bound_human_eligibility_and_exposure_attestations():
    bundle, queries, qrels = inputs()
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='gpt_generated', repeats=2, phase='final')
    with pytest.raises(ValueError, match='final.*attestation'):
        comparison.compare_conditions(bundle, trials_for(bundle), queries, qrels, protocol=protocol)


def test_frozen_criteria_cannot_be_replaced_or_relabel_scripted_as_full_system():
    bundle, _, _ = inputs()
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='historical_scripted')
    body = pipeline.verify(protocol)
    assert body['primary']['minimum_gain'] == .01
    assert body['primary']['normal_regression_maximum'] == 0
    assert body['primary']['comparators'] == ['no_repair', 'rules_plus']
    body['primary']['minimum_gain'] = 0
    _, queries, qrels = inputs()
    with pytest.raises(ValueError, match='criteria'):
        comparison.compare_conditions(bundle, trials_for(bundle), queries, qrels, protocol=pipeline.freeze(body))
    with pytest.raises(ValueError, match='full_system'):
        comparison.freeze_analysis_protocol(bundle, candidate_source='historical_scripted', study_scope='full_system')


def test_cli_assembly_blocks_labels_and_evaluator_then_separate_score(tmp_path, request):
    import tempfile
    root = Path(__file__).resolve().parents[1]
    (root / "work").mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=root / "work", prefix="test-comparison-")
    request.addfinalizer(temporary.cleanup)
    tmp_path = Path(temporary.name)
    bundle, queries, qrels = inputs()
    private = tmp_path / 'private'
    private.mkdir()
    paths = {'bundle': bundle, 'trials': trials_for(bundle),
             'protocol': comparison.freeze_analysis_protocol(bundle, candidate_source='mock')}
    for name, value in paths.items():
        (tmp_path / f'{name}.json').write_text(json.dumps(value), encoding="utf-8")
    (private / 'labels.json').write_text(json.dumps(dict(queries=queries, qrels=qrels)), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    script = root / 'scripts/compare_v5_conditions.py'
    common = [sys.executable, str(script)]
    # Declared protected label path is deliberately supplied as a trial input.
    blocked = subprocess.run(common + ['assemble', '--bundle', str(tmp_path / 'bundle.json'),
        '--protocol', str(tmp_path / 'protocol.json'), '--trials', str(private / 'labels.json'),
        '--protected-root', str(private), '--out', str(tmp_path / 'bad.json')], capture_output=True, text=True)
    assert blocked.returncode != 0 and 'private labels unavailable' in blocked.stderr
    assembled = subprocess.run(common + ['assemble', '--bundle', str(tmp_path / 'bundle.json'),
        '--protocol', str(tmp_path / 'protocol.json'), '--trials', str(tmp_path / 'trials.json'),
        '--protected-root', str(private), '--out', str(tmp_path / 'assembly.json')], capture_output=True, text=True)
    assert assembled.returncode == 0, assembled.stderr
    sealed = json.loads((tmp_path / 'assembly.json').read_text(encoding="utf-8"))
    assert pipeline.verify(sealed)['boundary'] == 'separate_CLI_invocation_declared_label_paths_denied'
    scored = subprocess.run(common + ['score', '--assembly', str(tmp_path / 'assembly.json'),
        '--labels', str(private / 'labels.json'), '--out', str(private / 'report.json'),
        '--bootstrap-samples', '20', '--random-repeats', '2'], capture_output=True, text=True)
    assert scored.returncode == 0, scored.stderr
    assert json.loads((private / 'report.json').read_text(encoding="utf-8"))['arms']['rubric:1']['apply_count'] == 2
    rerun = subprocess.run(common + ['score', '--assembly', str(tmp_path / 'assembly.json'),
        '--labels', str(private / 'labels.json'), '--out', str(private / 'report.json')], capture_output=True, text=True)
    assert rerun.returncode != 0 and 'FileExistsError' in rerun.stderr


def test_assembly_import_does_not_load_labels_or_evaluator():
    code = """
import sys
from searchclinic.research_v5 import comparison
assert 'searchclinic.research_v5.evaluation' not in sys.modules
assert 'searchclinic.corpus.evalset' not in sys.modules
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_protected_public_rules_generation_imports_no_private_label_modules():
    code = """
import sys
from searchclinic.research_v5.__main__ import protect
protect(['/tmp/nonexistent-private-label-root'])
from searchclinic.research.phase2.generation import build_context, generate_rules
assert 'searchclinic.corpus.evalset' not in sys.modules
assert 'searchclinic.patch.gate' not in sys.modules
assert 'searchclinic.evaluation.metrics' not in sys.modules
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_prospective_protocol_binds_implementation_and_bootstrap_configuration():
    bundle, _, _ = inputs()
    body = pipeline.verify(comparison.freeze_analysis_protocol(bundle, candidate_source='mock'))
    assert 'research_v5/comparison.py' in body['implementation']['source_files']
    assert 'research_v5/evaluation.py' in body['implementation']['source_files']
    assert body['bootstrap_samples'] == 2000
    assert body['random_repeats'] == 100
    assert body['bootstrap_seed'] == 20261030


def test_mock_transport_is_never_reported_as_a_real_llm_trial():
    result = compare(transport_summary={'transport': 'mocked_transport', 'provider_calls_executed': 0,
                                       'actual_cost_usd': 0})
    assert result['llm_experiment_status'] == 'NOT_EXECUTED_mocked_transport_only'
    assert result['arms']['no_repair']['apply_count'] == 0
    assert result['arms']['no_repair']['hold_count'] == 2
    assert result['paired_conditions']['rubric_vs_pair']['diagnostic_only'] is True


def test_harmful_acceptance_and_strict_normal_regression_are_measured():
    bundle, queries, qrels = inputs()
    body = pipeline.verify(bundle)
    body['documents'].append(dict(doc_id='good', name='alpha', category='sample',
                                 description='supporting correct product details ' + 'long ' * 40))
    body['records'][0]['context']['search_total'] = 1
    body['records'][0]['context']['observation']['result_count'] = 1
    queries[0]['stratum'] = 'healthy'
    qrels['q1'] = {'good': 1}
    bundle = pipeline.freeze(body)
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='mock')
    result = comparison.compare_conditions(bundle, trials_for(bundle), queries, qrels,
        protocol=protocol, bootstrap_samples=30, random_repeats=2)
    assert result['arms']['rubric:1']['harmful_accepted_count'] == 1
    assert result['arms']['rubric:1']['normal_regression_count'] == 1
    assert result['numerical_criteria_met'] is False


def test_corrupted_diagnostic_input_binding_is_rejected():
    bundle, queries, qrels = inputs()
    protocol = comparison.freeze_analysis_protocol(bundle, candidate_source='mock')
    assembly = comparison.assemble_comparison(bundle, trials_for(bundle), protocol=protocol)
    body = pipeline.verify(assembly)
    diagnostic = pipeline.verify(body['diagnostic'])
    diagnostic['input_hash'] = '0' * 64
    body['diagnostic'] = pipeline.freeze(diagnostic)
    with pytest.raises(ValueError, match='diagnostic'):
        comparison.score_comparison(pipeline.freeze(body), queries, qrels, bootstrap_samples=10)
