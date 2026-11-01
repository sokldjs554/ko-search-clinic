"""Real SQLite persistence; no paid calls or provider mocks needed."""
from decimal import Decimal

import pytest

from searchclinic.research.phase2.budget import DurableCallBudget


def budget(path, **overrides):
    config = dict(model='gpt-4.1-mini-2025-04-14', input_usd_million='.4',
                  output_usd_million='1.6', max_calls=2, usd_limit='.0096',
                  approved=True, experiment_hash='a' * 64)
    config.update(overrides)
    return DurableCallBudget(path, **config)


def test_unapproved_does_not_create_journal(tmp_path):
    path = tmp_path / 'calls.sqlite'
    with pytest.raises(PermissionError):
        budget(path, approved=False)
    assert not path.exists()


def test_pending_reservation_survives_restart_and_blocks_other_call(tmp_path):
    path = tmp_path / 'calls.sqlite'
    b = budget(path)
    b.reserve('q1', 6000)
    restarted = budget(path)
    assert Decimal(restarted.snapshot()['reserved_usd']) == Decimal('.0048')
    with pytest.raises(ValueError, match='pending'):
        restarted.reserve('q2', 6000)
    assert restarted.snapshot()['calls'] == 1


def test_usage_and_duplicate_prevention_survive_restart(tmp_path):
    path = tmp_path / 'calls.sqlite'
    b = budget(path)
    b.reserve('q1', 6000)
    b.settle('q1', 4000, 1000, model='gpt-4.1-mini-2025-04-14')
    restarted = budget(path)
    assert Decimal(restarted.snapshot()['spent_usd']) == Decimal('.0032')
    with pytest.raises(ValueError, match='retry'):
        restarted.reserve('q1', 6000)
    restarted.reserve('q2', 6000)
    restarted.settle('q2', 6000, 1500, model='gpt-4.1-mini-2025-04-14')
    with pytest.raises(ValueError, match='calls'):
        budget(path).reserve('q3', 6000)


@pytest.mark.parametrize('override', [dict(experiment_hash='b'*64), dict(max_calls=3),
                                      dict(usd_limit='1'), dict(input_usd_million='.3')])
def test_existing_journal_cannot_change_approved_parameters(tmp_path, override):
    path = tmp_path / 'calls.sqlite'
    budget(path)
    with pytest.raises(ValueError, match='configuration'):
        budget(path, **override)


def test_failed_and_overcap_calls_remain_reserved_after_restart(tmp_path):
    for method in ('fail', 'settle'):
        path = tmp_path / (method + '.sqlite')
        b = budget(path)
        b.reserve('q1', 6000)
        if method == 'fail':
            b.fail('q1', 'transport_error')
        else:
            with pytest.raises(ValueError, match='overcap'):
                b.settle('q1', 6001, 0, model='gpt-4.1-mini-2025-04-14')
        state = budget(path).snapshot()
        assert state['halted'] and Decimal(state['reserved_usd']) == Decimal('.0048')
        with pytest.raises(ValueError, match='halt'):
            budget(path).reserve('q2', 6000)


def test_two_instances_cannot_reserve_parallel_calls(tmp_path):
    path = tmp_path / 'calls.sqlite'
    first, second = budget(path), budget(path)
    first.reserve('q1', 6000)
    with pytest.raises(ValueError, match='pending'):
        second.reserve('q2', 6000)
    first.settle('q1', 1, 1, model='gpt-4.1-mini-2025-04-14')
    second.reserve('q2', 6000)
    assert first.snapshot()['calls'] == 2


def test_insufficient_money_does_not_reserve(tmp_path):
    b = budget(tmp_path/'calls.sqlite', usd_limit='.0047')
    with pytest.raises(ValueError, match='USD'):
        b.reserve('q1', 6000)
    assert b.snapshot()['calls'] == 0
