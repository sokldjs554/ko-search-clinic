"""Offline, frozen comparison assembly and separate private-label evaluation.

Assembly imports no evaluator and performs no provider calls. The CLI enforces
separate invocations with the project's declared-path audit hook; hashes are
integrity commitments, not proof of preregistration, blinding or human review.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import random
from statistics import mean, pstdev
from time import perf_counter

from . import pipeline

CONDITIONS = ('pair', 'context', 'rubric')
PRIMARY = {
    'condition': 'rubric', 'metric': 'ndcg10', 'population': 'overall',
    'repeat_aggregation': 'mean_within_query_before_cluster_bootstrap',
    'comparators': ['no_repair', 'rules_plus'], 'minimum_gain': .01,
    'familywise_alpha': .05, 'per_comparison_ci_level': .975,
    'success_rule': 'both_corrected_lower_bounds_at_least_minimum_gain_and_zero_normal_regressions',
    'normal_regression_maximum': 0,
    'normal_regression_definition': 'any_healthy_query_any_metric_loss_above_1e-12_in_any_primary_repeat',
    'posthoc_tuning_allowed': False,
}
ATTESTATIONS = ('eligibility_verified', 'human_review_complete', 'exposure_audit_complete',
                'independent_concepts_verified', 'frozen_before_final_outcomes',
                'candidate_generation_verified')


def _implementation():
    root = Path(__file__).resolve().parents[1]
    names = ('research_v5/comparison.py', 'research_v5/evaluation.py', 'research_v5/run_evidence.py', 'research_v5/transport.py',
             'research/phase2/generation.py', 'research/observations.py', 'research/detector.py',
             'doctor/__init__.py', 'doctor/rules_plus.py', 'doctor/scripted.py', 'doctor/tools.py')
    sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    return dict(source_files=sources, source_hash=pipeline.freeze(sources)['sha256'],
                application_runtime=pipeline._runtime())


def freeze_analysis_protocol(bundle, *, candidate_source, study_scope='selection_only',
                             repeats=2, phase='development'):
    """Commit criteria before outcomes. The caller must retain the original seal."""
    body, _, _ = pipeline._bundle(bundle)
    if candidate_source not in ('historical_scripted', 'gpt_generated', 'mock'):
        raise ValueError('candidate_source must identify historical_scripted, gpt_generated or mock')
    if study_scope not in ('selection_only', 'full_system'):
        raise ValueError('unsupported study scope')
    if study_scope == 'full_system' and candidate_source != 'gpt_generated':
        raise ValueError('full_system requires actual GPT generation provenance')
    if type(repeats) is not int or repeats < 2:
        raise ValueError('at least two frozen repeats required')
    if phase not in ('development', 'final'):
        raise ValueError('invalid study phase')
    return pipeline.freeze(dict(version='comparison-protocol-v5', input_hash=bundle['sha256'],
        candidate_source=candidate_source, study_scope=study_scope, repeats=repeats, phase=phase,
        conditions=list(CONDITIONS), min_confidence=body['min_confidence'], primary=PRIMARY,
        implementation=_implementation(), bootstrap_samples=2000, random_repeats=100, bootstrap_seed=20261030,
        threshold_diagnostic=[0., .5, .8, .9, 1.],
        selection_policy='highest_minimum_patch_confidence_then_original_index',
        rules_plus_policy='fresh_public_retrieval_context;existing_rules_generator;first_valid;no_qrels_gate'))


def _protocol(protocol, bundle=None):
    body = pipeline.verify(protocol)
    if bundle is not None:
        expected = pipeline.verify(freeze_analysis_protocol(bundle,
            candidate_source=body.get('candidate_source'), study_scope=body.get('study_scope'),
            repeats=body.get('repeats'), phase=body.get('phase')))
        if body != expected:
            raise ValueError('frozen analysis criteria or input binding changed')
    elif (body.get('primary') != PRIMARY or body.get('version') != 'comparison-protocol-v5'
          or body.get('implementation') != _implementation()
          or (body.get('bootstrap_samples'), body.get('random_repeats'), body.get('bootstrap_seed')) != (2000, 100, 20261030)):
        raise ValueError('frozen analysis criteria changed')
    return body


def _final_gate(protocol, attestations, *, human_semantics=None, scoring=False):
    body = _protocol(protocol)
    if body['phase'] != 'final':
        return
    if attestations is None:
        raise ValueError('final analysis blocked: missing eligibility/human review/exposure attestations')
    attested = pipeline.verify(attestations)
    if (attested.get('input_hash') != body['input_hash']
            or attested.get('protocol_hash') != protocol['sha256']
            or any(attested.get(k) is not True for k in ATTESTATIONS)
            or body['candidate_source'] != 'gpt_generated'):
        raise ValueError('final analysis blocked: incomplete or unbound attestations')
    if scoring and human_semantics is None:
        raise ValueError('final analysis blocked: human semantic labels required')


def _trials(trials, body, records):
    if not isinstance(trials, list):
        raise ValueError('trials must be a complete list')
    expected = {(condition, repeat) for condition in CONDITIONS for repeat in range(1, body['repeats'] + 1)}
    seen = set()
    for trial in trials:
        if not isinstance(trial, dict) or set(trial) != {'condition', 'repeat', 'input_hash', 'verdicts'}:
            raise ValueError('trial requires condition, repeat, input_hash and verdicts only')
        key = (trial['condition'], trial['repeat'])
        if type(trial['repeat']) is not int or key not in expected or key in seen:
            raise ValueError('duplicate or unexpected condition/repeat')
        seen.add(key)
        if trial['input_hash'] != body['input_hash']:
            raise ValueError('trial candidate input hash mismatch')
        if not isinstance(trial['verdicts'], dict) or set(trial['verdicts']) != set(records):
            raise ValueError('trial verdicts require exact query coverage')
        for qid, (_, record) in records.items():
            values = trial['verdicts'][qid]
            if not isinstance(values, list) or len(values) != len(record['candidates']):
                raise ValueError('trial verdicts require exact candidate alignment; use null for missing')
    if seen != expected:
        raise ValueError('missing condition/repeat trials')


def _rules_bundle(bundle):
    from searchclinic.index.engine import SearchEngine
    from searchclinic.research.phase2.generation import build_context, generate_rules
    body, docs, records = pipeline._bundle(bundle)
    base = SearchEngine(list(docs.values()))
    output, generation = [], []
    for qid, (original, _) in records.items():
        context = build_context(base, qid, original.query)
        generated = generate_rules(context)
        generation.append(generated)
        output.append(dict(context=context.model_dump(mode='json'),
                           candidates=[c['prescription'] for c in generated['candidates']],
                           generation_error=None if generated['error'] is None else str(generated['error'])))
    body['records'] = output
    return pipeline.freeze(body), generation


def _threshold_choices(application, diagnostic, thresholds):
    """Reconsider confidence only; every other semantic/application check remains."""
    result = {}
    for threshold in thresholds:
        selected = {}
        for qid, row in application['decisions'].items():
            eligible = [c for c in row['candidate_decisions']
                        if c['confidence'] is not None and c['confidence'] >= threshold
                        and not (set(c['errors']) - {'low_confidence'})
                        and str(c['candidate_index']) in diagnostic['rankings'][qid]]
            selected[qid] = (str(min(eligible, key=lambda c: (-c['confidence'], c['candidate_index']))['candidate_index'])
                             if eligible else None)
        result[str(threshold)] = selected
    return result


def assemble_comparison(bundle, trials, *, protocol, attestations=None, transport_summary=None, transport_evidence=None):
    """Freeze applications, random-free diagnostics, and RulesPlus BEFORE labels.

    Use the CLI ``assemble --protected-root`` to deny declared label paths. This
    Python function by itself cannot remove data already loaded by its caller.
    """
    start = perf_counter()
    body = _protocol(protocol, bundle)
    _final_gate(protocol, attestations)
    if transport_evidence is not None:
        from .run_evidence import validate_run
        checked = validate_run(transport_evidence, bundle, require_complete=body['phase']=='final')
        if trials != checked['trials']:
            raise ValueError('supplied trials differ from verified raw evidence')
        if transport_summary is not None and transport_summary != checked['summary']:
            raise ValueError('supplied summary differs from verified raw evidence')
        transport_summary = checked['summary']
    elif body['phase'] == 'final':
        raise ValueError('final analysis blocked: verified raw provider evidence required')
    _, _, records = pipeline._bundle(bundle)
    _trials(trials, body, records)
    applications, timings = {}, {}
    for trial in trials:
        name = f"{trial['condition']}:{trial['repeat']}"
        began = perf_counter()
        applications[name] = pipeline.apply_candidates(bundle, trial['verdicts'], condition=trial['condition'])
        timings[name] = (perf_counter() - began) * 1000
    empty = {qid: [] for qid in records}
    applications['first_valid'] = pipeline.apply_candidates(bundle, empty, policy='first_valid')
    diagnostic = pipeline.diagnostic_candidates(bundle)
    rules_bundle, generated = _rules_bundle(bundle)
    if body['study_scope'] == 'full_system':
        original_contexts = {r['context']['query_id']: r['context'] for r in pipeline.verify(bundle)['records']}
        public_contexts = {r['context']['query_id']: r['context'] for r in pipeline.verify(rules_bundle)['records']}
        if original_contexts != public_contexts:
            raise ValueError('full_system requires identical fresh public generator contexts for GPT and RulesPlus')
    applications['rules_plus'] = pipeline.apply_candidates(rules_bundle, empty, policy='first_valid')
    rules_diagnostic = pipeline.diagnostic_candidates(rules_bundle)
    thresholds = {name: _threshold_choices(pipeline.verify(app), pipeline.verify(diagnostic), body['threshold_diagnostic'])
                  for name, app in applications.items() if ':' in name}
    return pipeline.freeze(dict(version='comparison-assembly-v5', protocol=protocol,
        input_hash=bundle['sha256'], applications=applications, diagnostic=diagnostic,
        rules_diagnostic=rules_diagnostic, rules_bundle_hash=rules_bundle['sha256'],
        generation_counts={qid: len(record['candidates']) for qid, (_, record) in records.items()},
        thresholds=thresholds, attestations=attestations, transport_evidence=transport_evidence,
        costs=dict(comparison_provider_calls=0, application_latency_ms=timings,
                   assembly_latency_ms=(perf_counter() - start) * 1000,
                   rules_generation=[r['costs'] for r in generated],
                   transport=transport_summary),
        rules_plus=dict(context_policy='fresh_public_retrieval_context',
                        generator='existing_phase2_generate_rules', selector='first_valid',
                        context_hashes={r['query_id']: r['context_hash'] for r in generated}),
        boundary='library_assembly_no_label_arguments;CLI_protected_separate_invocation_required'))


def _paired(scores, baseline, queries, *, bootstrap_samples, seed, ci_level=.975):
    from .evaluation import METRICS, _percentile
    differences = {q: {m: scores[q][m] - baseline[q][m] for m in METRICS} for q in scores}
    grouped = defaultdict(list)
    for query in queries:
        grouped[query['concept_id']].append(query['query_id'])
    clusters = [grouped[key] for key in sorted(grouped)]
    draws = {m: [] for m in METRICS}
    if len(clusters) >= 2:
        rng = random.Random(seed)
        for _ in range(bootstrap_samples):
            sample = [q for cluster in rng.choices(clusters, k=len(clusters)) for q in cluster]
            for metric in METRICS:
                draws[metric].append(mean(differences[q][metric] for q in sample))
    tail = (1 - ci_level) / 2
    return dict(ci_level=ci_level, correction='Bonferroni_two_prespecified_primary_comparisons' if ci_level == .975 else 'none_exploratory',
        independent_groups=len(clusters), per_query=differences,
        metrics={m: dict(mean_difference=mean(row[m] for row in differences.values()),
            ci=[_percentile(sorted(draws[m]), tail), _percentile(sorted(draws[m]), 1 - tail)] if draws[m] else None)
                 for m in METRICS},
        interpretation='descriptive_only_unless_final_eligibility_verified')


def _human_labels(labels, candidate_scores, *, required=False):
    if labels is None:
        return {}
    if not isinstance(labels, dict) or set(labels) - set(candidate_scores):
        raise ValueError('human semantic labels contain unknown queries')
    for qid, values in labels.items():
        if not isinstance(values, dict) or set(values) - set(candidate_scores[qid]):
            raise ValueError('human semantic labels contain unknown valid candidates')
        if any(type(value) is not bool and value is not None for value in values.values()):
            raise ValueError('human semantic labels must be boolean or null, never qrels grades')
    if required and (set(labels) != set(candidate_scores) or any(
            set(labels[q]) != set(c) or any(v is None for v in labels[q].values()) for q, c in candidate_scores.items())):
        raise ValueError('final requires complete human semantic candidate labels')
    return labels


def _arm_summary(application, scores, baseline, candidate_scores, labels, queries, counts):
    from .evaluation import METRICS, oracle_analysis
    selected = {q: None if d['candidate_index'] is None else str(d['candidate_index'])
                for q, d in application['decisions'].items()}
    oracle = oracle_analysis({q: v['ndcg10'] for q, v in baseline.items()}, candidate_scores, selected)
    reasons = Counter(error.split(':', 1)[0] for d in application['decisions'].values()
                      for c in d['candidate_decisions'] for error in c['errors'])
    accepted = [q for q in selected if selected[q] is not None]
    semantic = [labels.get(q, {}).get(selected[q]) for q in accepted]
    normal = [q['query_id'] for q in queries if q['stratum'] == 'healthy']
    return dict(apply_count=len(accepted), hold_count=len(selected) - len(accepted),
        selected=selected, reason_counts=dict(reasons), malformed_verdict_count=reasons['malformed_verdict'],
        missing_verdict_count=reasons['missing_verdict'], invalid_candidate_count=reasons['invalid_candidate'],
        application_error_count=reasons['application_error'],
        generation_error_count=sum(d['generation_error'] is not None for d in application['decisions'].values()),
        generation_missing_count=sum(value == 0 for value in counts.values()),
        generation_abstention_count=sum(counts[q] == 0 and d['generation_error'] is None
                                        for q, d in application['decisions'].items()),
        useful_candidate_false_hold_count=sum(selected[q] is None and row['available_gain'] > 1e-12
                                             for q, row in oracle['per_query'].items()),
        harmful_accepted_count=sum(any(scores[q][m] < baseline[q][m] - 1e-12 for m in METRICS) for q in accepted),
        normal_regression_count=sum(any(scores[q][m] < baseline[q][m] - 1e-12 for m in METRICS) for q in normal),
        oracle_diagnostic=oracle,
        semantic_correctness=dict(status='human_labeled' if semantic and all(v is not None for v in semantic) else 'UNKNOWN',
            correct_count=sum(v is True for v in semantic) if any(v is not None for v in semantic) else None,
            incorrect_count=sum(v is False for v in semantic) if any(v is not None for v in semantic) else None,
            unknown_count=sum(v is None for v in semantic)))


def score_comparison(assembly, queries, qrels, *, human_semantics=None, bootstrap_samples=2000,
                     random_repeats=100, seed=20261030):
    """Read private labels only after the complete application assembly is sealed."""
    from .evaluation import METRICS, _metrics, matched_random_selection, score_runs
    assembled = pipeline.verify(assembly)
    if assembled.get('version') != 'comparison-assembly-v5':
        raise ValueError('expected frozen comparison assembly')
    protocol = assembled['protocol']
    criteria = _protocol(protocol)
    _final_gate(protocol, assembled['attestations'], human_semantics=human_semantics, scoring=True)
    if criteria['phase'] == 'final':
        from .run_evidence import validate_run
        raw_evidence = assembled.get('transport_evidence')
        if raw_evidence is None:
            raise ValueError('final analysis blocked: verified raw provider evidence required')
        evidence_body = pipeline.verify(raw_evidence)
        validate_run(raw_evidence, evidence_body['plan']['body']['bundle'], require_complete=True)
        if (evidence_body['plan']['body']['input_hash'] != assembled['input_hash']
                or evidence_body['summary'] != assembled['costs']['transport']):
            raise ValueError('final transport evidence binding mismatch')

    if criteria['phase'] == 'final' and (bootstrap_samples, random_repeats, seed) != (
            criteria['bootstrap_samples'], criteria['random_repeats'], criteria['bootstrap_seed']):
        raise ValueError('final analysis requires frozen bootstrap and random configuration')
    if type(random_repeats) is not int or random_repeats < 1:
        raise ValueError('random_repeats must be a positive integer')
    apps = {name: pipeline.verify(app) for name, app in assembled['applications'].items()}
    expected = {f'{c}:{r}' for c in CONDITIONS for r in range(1, criteria['repeats'] + 1)} | {'first_valid', 'rules_plus'}
    if set(apps) != expected or assembled['input_hash'] != criteria['input_hash']:
        raise ValueError('assembly coverage or protocol input mismatch')
    diagnostics = {key: pipeline.verify(assembled[key]) for key in ('diagnostic', 'rules_diagnostic')}
    base = apps['first_valid']['baseline_rankings']
    for name, diagnostic in diagnostics.items():
        expected_hash = assembled['rules_bundle_hash'] if name == 'rules_diagnostic' else assembled['input_hash']
        if (diagnostic.get('input_hash') != expected_hash or diagnostic.get('baseline_rankings') != base
                or diagnostic.get('runtime') != pipeline._runtime()):
            raise ValueError('diagnostic input, baseline or implementation mismatch')
    for name, app in apps.items():
        expected_hash = assembled['rules_bundle_hash'] if name == 'rules_plus' else assembled['input_hash']
        if app['input_hash'] != expected_hash or app['baseline_rankings'] != base:
            raise ValueError('application input or baseline mismatch')
        pipeline.score_application(assembled['applications'][name], queries, qrels,
                                   bootstrap_samples=bootstrap_samples, seed=seed)
    arms = {'no_repair': base, **{name: app['rankings'] for name, app in apps.items()}}
    scores = score_runs(queries, qrels, arms, bootstrap_samples=bootstrap_samples, seed=seed)
    if criteria['phase'] == 'final' and ({q['stratum'] for q in queries} != {'failure', 'healthy'}
            or len({q['concept_id'] for q in queries}) < 2):
        raise ValueError('final analysis requires failure and healthy populations and independent groups')
    baseline = scores['per_query']['no_repair']
    candidate_scores = {key: {q: {cid: _metrics(rank, qrels[q])['ndcg10'] for cid, rank in values.items()}
                                    for q, values in diagnostic['rankings'].items()}
                        for key, diagnostic in diagnostics.items()}
    labels = _human_labels(human_semantics, candidate_scores['diagnostic'], required=criteria['phase'] == 'final')
    summaries = {}
    for name, app in apps.items():
        is_rules = name == 'rules_plus'
        counts = ({q: len(row['candidate_decisions']) for q, row in app['decisions'].items()}
                  if is_rules else assembled['generation_counts'])
        summaries[name] = _arm_summary(app, scores['per_query'][name], baseline,
            candidate_scores['rules_diagnostic' if is_rules else 'diagnostic'],
            {} if is_rules else labels, queries, counts)
    summaries['first_valid']['description'] = ('GPT basic first_valid selector baseline' if criteria['candidate_source'] == 'gpt_generated'
        else f"{criteria['candidate_source']} first_valid selector baseline; not GPT generation")
    summaries['no_repair'] = dict(apply_count=0, hold_count=len(base), description='immutable base retrieval')
    averages = {condition: {q: {m: mean(scores['per_query'][f'{condition}:{r}'][q][m] for r in range(1, criteria['repeats'] + 1))
                   for m in METRICS} for q in baseline} for condition in CONDITIONS}
    average = averages['rubric']
    paired = {f'vs_{name}': _paired(average, scores['per_query'][name], queries,
                                  bootstrap_samples=bootstrap_samples, seed=seed)
              for name in ('no_repair', 'rules_plus')}
    paired_conditions = {f'{a}_vs_{b}': dict(diagnostic_only=True, **_paired(averages[a], averages[b], queries,
        bootstrap_samples=bootstrap_samples, seed=seed, ci_level=.95))
        for a, b in [('context', 'pair'), ('rubric', 'pair'), ('rubric', 'context')]}
    variability = {}
    for condition in CONDITIONS:
        names = [f'{condition}:{r}' for r in range(1, criteria['repeats'] + 1)]
        means = [scores['summaries'][name]['overall']['ndcg10'] for name in names]
        variability[condition] = dict(repeats=len(names), mean_ndcg10=mean(means),
            population_sd_ndcg10=pstdev(means), range_ndcg10=[min(means), max(means)],
            changed_selection_query_count=sum(len({summaries[n]['selected'][q] for n in names}) > 1 for q in baseline),
            per_query={q: dict(mean_ndcg10=mean(scores['per_query'][n][q]['ndcg10'] for n in names),
                              population_sd_ndcg10=pstdev(scores['per_query'][n][q]['ndcg10'] for n in names)) for q in baseline})
    eligible = {q: list(c) for q, c in candidate_scores['diagnostic'].items()}
    random_rows = {}
    for name in sorted(n for n in apps if n != 'rules_plus'):
        rows = []
        for repeat in range(random_repeats):
            selected = matched_random_selection(eligible, summaries[name]['apply_count'], seed + repeat)
            rankings = {q: diagnostics['diagnostic']['rankings'][q][selected[q]] if q in selected else base[q] for q in base}
            values = {q: _metrics(rank, qrels[q]) for q, rank in rankings.items()}
            rows.append(dict(seed=seed + repeat, apply_count=len(selected), selected=selected,
                mean_ndcg10=mean(v['ndcg10'] for v in values.values()),
                per_query_differences={q: {m: values[q][m] - baseline[q][m] for m in METRICS} for q in base}))
        random_rows[name] = rows
    sweep = {}
    for name, thresholds in assembled['thresholds'].items():
        sweep[name] = {threshold: dict(apply_count=sum(c is not None for c in selected.values()),
            mean_ndcg10=mean(candidate_scores['diagnostic'][q][c] if c is not None else baseline[q]['ndcg10']
                              for q, c in selected.items())) for threshold, selected in thresholds.items()}
    safety = all(summaries[f'rubric:{r}']['normal_regression_count'] == 0 for r in range(1, criteria['repeats'] + 1))
    meets = safety and all(row['metrics']['ndcg10']['ci'] is not None and
                           row['metrics']['ndcg10']['ci'][0] >= PRIMARY['minimum_gain'] for row in paired.values())
    transport = assembled['costs']['transport'] or {}
    llm_status = ('NOT_EXECUTED_mocked_transport_only' if transport.get('transport') == 'mocked_transport'
                  or criteria['candidate_source'] == 'mock' else
                  ('provider_transport_partial' if transport.get('status')=='stopped' else 'provider_transport_recorded') if assembled.get('transport_evidence') is not None and transport.get('transport') == 'provider_transport' else
                  'UNVERIFIED_supplied_verdicts_only')
    return dict(version='comparison-report-v5', assembly_hash=assembly['sha256'], protocol_hash=protocol['sha256'],
        input_hash=assembled['input_hash'], study_scope=criteria['study_scope'], phase=criteria['phase'],
        candidate_source=criteria['candidate_source'], llm_experiment_status=llm_status,
        analysis_configuration=dict(bootstrap_samples=bootstrap_samples, random_repeats=random_repeats, seed=seed,
                                    development_overrides=(bootstrap_samples, random_repeats, seed) != (2000, 100, 20261030)),
        study_status='mock_orchestration_only' if criteria['candidate_source'] == 'mock' else
            ('retrospective_scripted_selection_only' if criteria['candidate_source'] == 'historical_scripted' else 'provided_GPT_candidate_comparison'),
        scores=scores, arms=summaries, paired_primary=paired, paired_conditions=paired_conditions, repeat_variability=variability,
        matched_random=random_rows, rules_plus=assembled['rules_plus'], costs=assembled['costs'],
        threshold_diagnostic=dict(interpretation='diagnostic_only_not_optimal_threshold_or_probability', rows=sweep),
        prospective_criteria=PRIMARY, numerical_criteria_met=meets,
        superiority_claim=bool(meets and criteria['phase'] == 'final'),
        limitations=['Hashes do not prove temporal preregistration, provenance, independence or human review.',
            'Selection-only estimates condition on supplied candidates; historical scripted submissions were outcome-filtered.',
            'RulesPlus generates separate candidates from fresh public retrieval context; it is not a same-candidate selector.',
            'Qrels measure retrieval utility only; missing human semantic labels remain UNKNOWN.',
            'Repeated judgments share queries: average within query before concept-cluster bootstrap.',
            'Confidence sweep is a fixed diagnostic, not a fitted probability or threshold recommendation.',
            'No cumulative global deployment: patches apply to each target from pristine base.'])


def compare_conditions(bundle, trials, queries, qrels, *, protocol, human_semantics=None,
                       attestations=None, transport_summary=None, **kwargs):
    """Development convenience only; use separate CLI phases for label isolation."""
    assembly = assemble_comparison(bundle, trials, protocol=protocol, attestations=attestations,
                                   transport_summary=transport_summary)
    result = score_comparison(assembly, queries, qrels, human_semantics=human_semantics, **kwargs)
    result['boundary'] = 'in_process_development_convenience_not_label_isolated'
    return result
