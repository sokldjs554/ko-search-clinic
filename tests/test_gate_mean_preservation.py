"""Catch small distributed regressions hidden by the per-query epsilon."""
from types import SimpleNamespace
import pytest
from searchclinic.corpus.evalset import EvalQuery
from searchclinic.evaluation.metrics import QueryMetrics
from searchclinic.patch.ir import Prescription
from searchclinic.patch.gate import run_gate
from searchclinic.analysis.config import AnalyzerConfig


def exercise(monkeypatch, **kwargs):
    import searchclinic.patch.gate as gate
    queries = [EvalQuery(query=f'q{i}', qrels={'d': 1}) for i in range(5)]
    before = {q.query: QueryMetrics(q.query, .5, .5, .5, 1, ('d',)) for q in queries}
    values = kwargs.pop('after_values', [.55, .481, .481, .481, .481])
    after = {q.query: QueryMetrics(q.query, values[i], .5, .5, 1, ('d',))
             for i, q in enumerate(queries)}
    sandbox = object()
    engine = SimpleNamespace(config=AnalyzerConfig(), with_config=lambda _: sandbox)
    def evaluate(e, _, **options):
        assert options.get('round_metrics') is False
        return before if e is engine else after
    monkeypatch.setattr(gate, 'evaluate_all', evaluate)
    rx = Prescription(target_query='q0', diagnosis_family='spelling_variant',
                      reasoning='controlled aggregate regression example',
                      synonym_groups=[{'terms': ['a', 'b']}])
    return run_gate(engine, queries, rx, **kwargs)[0]


def test_distributed_small_losses_cannot_reduce_mean(monkeypatch):
    verdict = exercise(monkeypatch)
    assert verdict.target_after.ndcg > verdict.target_before.ndcg
    assert not verdict.regressions  # each loss is within 0.02
    assert verdict.mean_after < verdict.mean_before
    assert not verdict.accepted
    assert '평균' in verdict.reason


def test_legacy_mean_tolerance_requires_explicit_opt_in(monkeypatch):
    assert exercise(monkeypatch, mean_epsilon=.02).accepted


def test_rounding_the_report_mean_must_not_hide_loss(monkeypatch):
    verdict = exercise(monkeypatch, after_values=[.55, .4875, .4875, .4875, .4874])
    assert not verdict.accepted


def test_gate_can_request_full_precision_without_changing_default_metrics():
    from searchclinic.evaluation.metrics import evaluate_query
    import math
    engine = SimpleNamespace(search=lambda query, k: [SimpleNamespace(doc_id='wrong'),
                                                     SimpleNamespace(doc_id='right')])
    query = EvalQuery(query='q', qrels={'right': 1})
    assert evaluate_query(engine, query).ndcg == .6309
    assert evaluate_query(engine, query, round_metrics=False).ndcg == 1 / math.log2(3)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -.01])
def test_invalid_mean_tolerances_rejected(monkeypatch, bad):
    with pytest.raises(ValueError):
        exercise(monkeypatch, mean_epsilon=bad)
