"""Bounded, label-free post-hoc development selector for empty baseline results.

Semantic confidence is not a probability of retrieval improvement. Only when the
baseline has no results, require an eligible candidate to produce a result. Keep
the original confidence/index order otherwise. Nonempty does not mean relevant.
"""
import copy
import hashlib
from pathlib import Path

from . import pipeline

VERSION = 'zero-hit-aware-v5-development'


def choose(baseline, rankings, decision):
    if baseline:
        return decision['candidate_index']
    eligible = [c for c in decision['candidate_decisions']
                if c['eligible'] and rankings.get(str(c['candidate_index']))]
    return min(eligible, key=lambda c: (-c['confidence'], c['candidate_index']))['candidate_index'] if eligible else None


def assemble(source):
    body = pipeline.verify(source)
    if body['version'] != 'comparison-assembly-v5' or pipeline.verify(body['protocol'])['phase'] != 'development':
        raise ValueError('post-hoc selector only accepts a development comparison')
    diagnostic = pipeline.verify(body['diagnostic'])
    base = body['applications']['first_valid']['body']['baseline_rankings']
    if diagnostic['baseline_rankings'] != base or diagnostic['input_hash'] != body['input_hash']:
        raise ValueError('source diagnostic binding mismatch')
    arms = {}
    for name, sealed in body['applications'].items():
        if ':' not in name:
            continue
        app = pipeline.verify(sealed)
        if app['baseline_rankings'] != base or app['input_hash'] != body['input_hash']:
            raise ValueError('source application binding mismatch')
        decisions = copy.deepcopy(app['decisions'])
        rankings = {}
        changed = []
        for qid, decision in decisions.items():
            selected = choose(base[qid], diagnostic['rankings'][qid], decision)
            if selected != decision['candidate_index']:
                changed.append(qid)
            decision['candidate_index'] = selected
            decision['status'] = 'selected' if selected is not None else 'held'
            rankings[qid] = base[qid] if selected is None else diagnostic['rankings'][qid][str(selected)]
        arms[name] = dict(decisions=decisions, rankings=rankings, changed_queries=changed)
    return pipeline.freeze(dict(version=VERSION, stage='posthoc_development_only_not_primary',
        source=source, source_hash=source['sha256'], arms=arms,
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        additional_provider_calls=0))


def score(selection, queries, qrels):
    from .comparison import _arm_summary, _paired
    from .evaluation import score_runs, _metrics
    body = pipeline.verify(selection)
    if assemble(body['source']) != selection:
        raise ValueError('selection or implementation binding mismatch')
    source = pipeline.verify(body['source'])
    base = source['applications']['first_valid']['body']['baseline_rankings']
    runs = {'no_repair':base, 'rules_plus':source['applications']['rules_plus']['body']['rankings'],
            'first_valid':source['applications']['first_valid']['body']['rankings'],
            **{name:app['rankings'] for name,app in body['arms'].items()}}
    scores = score_runs(queries,qrels,runs,bootstrap_samples=2000,seed=20261030)
    candidate_scores = {q:{cid:_metrics(rank,qrels[q])['ndcg10'] for cid,rank in values.items()}
                        for q,values in source['diagnostic']['body']['rankings'].items()}
    arms = {name:_arm_summary(app,scores['per_query'][name],scores['per_query']['no_repair'],
                candidate_scores,{},queries,source['generation_counts']) for name,app in body['arms'].items()}
    return dict(version=VERSION,stage=body['stage'],selection_hash=selection['sha256'],
        source_hash=body['source_hash'],additional_provider_calls=0,superiority_claim=False,
        scores=scores,arms=arms,changed_query_counts={name:len(app['changed_queries']) for name,app in body['arms'].items()},
        exploratory_pair_vs_rules={name:_paired(scores['per_query'][name],scores['per_query']['rules_plus'],
            queries,bootstrap_samples=2000,seed=20261030,ci_level=.95) for name in ('pair:1','pair:2')})
