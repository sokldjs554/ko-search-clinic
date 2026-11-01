"""Offline reservation guard. No key handling, transport or API calls."""
from decimal import Decimal
from contextlib import contextmanager
import json
import sqlite3


class CallBudget:
    def __init__(self, model, input_usd_million, output_usd_million, max_calls, usd_limit, approved=False):
        self.model = model
        self.input_price, self.output_price = Decimal(input_usd_million), Decimal(output_usd_million)
        self.usd_limit = Decimal(usd_limit)
        if (not model or type(max_calls) is not int or max_calls<1 or any(
                not x.is_finite() or x<=0 for x in (self.input_price,self.output_price,self.usd_limit))):
            raise ValueError('known positive model prices and budget required')
        self.max_calls, self.approved = max_calls, approved
        self.spent = self.reserved = Decimal(0)
        self.calls, self.halted, self.entries = 0, False, {}

    def cost(self, inputs, outputs):
        return (self.input_price*inputs+self.output_price*outputs)/Decimal(1000000)

    def reserve(self, query_id, input_bound):
        if not self.approved:
            raise PermissionError('separate paid-experiment approval required')
        if self.halted:
            raise ValueError('budget halted')
        if query_id in self.entries:
            raise ValueError('query retry forbidden')
        if self.calls >= self.max_calls:
            raise ValueError('maximum calls reached')
        if type(input_bound) is not int or not 0<=input_bound<=6000:
            raise ValueError('verified input token bound required, cap 6000')
        amount = self.cost(input_bound,1500)
        if self.spent+self.reserved+amount > self.usd_limit:
            raise ValueError('USD reservation limit exceeded')
        self.entries[query_id]={'reserved':amount,'input_bound':input_bound,'status':'reserved'}
        self.reserved+=amount
        self.calls+=1
        return amount

    def settle(self, query_id, inputs, outputs, model):
        entry=self.entries[query_id]
        if self.halted or entry['status']!='reserved':
            raise ValueError('halted or already settled')
        if model!=self.model:
            self.halted=True
            raise ValueError('model substitution forbidden')
        if (type(inputs) is not int or type(outputs) is not int or
                not 0<=inputs<=entry['input_bound'] or not 0<=outputs<=1500):
            self.halted=True
            raise ValueError('unknown or overcap usage; reservation retained')
        self.reserved-=entry['reserved']
        self.spent+=self.cost(inputs,outputs)
        entry.update(status='settled',inputs=inputs,outputs=outputs)

    def fail(self, query_id, reason):
        entry=self.entries[query_id]
        if entry['status']!='reserved':
            raise ValueError('call not pending')
        entry.update(status='error',error=reason)
        self.halted=True


class DurableCallBudget:
    """Persist reservations BEFORE transport, with no automatic crash retry.

    One SQLite journal belongs to one approved, frozen experiment. Reopening
    cannot change its configuration. A pending request blocks every new request:
    after a crash its billing is unknown, so an operator must reconcile evidence.
    This is an execution safeguard, not evidence that approval was obtained.
    The caller must authenticate approval and use the same journal on every run.
    """

    def __init__(self, path, *, experiment_hash, approved=False, **config):
        if approved is not True:
            raise PermissionError('separate paid-experiment approval required')
        if (not isinstance(experiment_hash, str) or len(experiment_hash) != 64
                or any(c not in '0123456789abcdef' for c in experiment_hash)):
            raise ValueError('frozen experiment SHA256 required')
        self.path = str(path)
        self.config = dict(config, approved=True)
        initial = CallBudget(**self.config)
        # Canonical decimal spelling prevents equivalent prices causing drift.
        self.identity = json.dumps(dict(
            experiment_hash=experiment_hash, model=initial.model,
            input_usd_million=str(initial.input_price.normalize()),
            output_usd_million=str(initial.output_price.normalize()),
            max_calls=initial.max_calls, usd_limit=str(initial.usd_limit.normalize())),
            sort_keys=True)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS budget '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL, state TEXT NOT NULL)')
            row = db.execute('SELECT identity FROM budget WHERE id=1').fetchone()
            if row is None:
                db.execute('INSERT INTO budget VALUES (1, ?, ?)',
                           (self.identity, self._encode(initial)))
            elif row[0] != self.identity:
                raise ValueError('journal configuration differs from frozen experiment')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _encode(budget):
        return json.dumps(dict(spent=str(budget.spent), reserved=str(budget.reserved),
            calls=budget.calls, halted=budget.halted, entries={key: dict(value,
                reserved=str(value['reserved'])) for key, value in budget.entries.items()}),
            sort_keys=True, allow_nan=False)

    def _load(self, db):
        identity, raw = db.execute('SELECT identity, state FROM budget WHERE id=1').fetchone()
        if identity != self.identity:
            raise ValueError('journal configuration changed')
        state = json.loads(raw)
        budget = CallBudget(**self.config)
        budget.spent, budget.reserved = Decimal(state['spent']), Decimal(state['reserved'])
        budget.calls, budget.halted = state['calls'], state['halted']
        budget.entries = {k: dict(v, reserved=Decimal(v['reserved']))
                          for k, v in state['entries'].items()}
        return budget

    def _mutate(self, operation, *args, **kwargs):
        error, result = None, None
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            budget = self._load(db)
            try:
                if operation == 'reserve' and not budget.halted:
                    if any(e['status'] == 'reserved' for e in budget.entries.values()):
                        raise ValueError('pending call requires reconciliation; no automatic retry')
                result = getattr(budget, operation)(*args, **kwargs)
            except (ValueError, PermissionError) as exc:
                # Settle can halt on unknown billing. Persist that halt even when
                # raising, instead of rolling the safety state back with the error.
                error = exc
            db.execute('UPDATE budget SET state=? WHERE id=1', (self._encode(budget),))
        if error is not None:
            raise error
        return result

    def reserve(self, query_id, input_bound):
        return self._mutate('reserve', query_id, input_bound)

    def settle(self, query_id, inputs, outputs, model):
        return self._mutate('settle', query_id, inputs, outputs, model)

    def fail(self, query_id, reason):
        return self._mutate('fail', query_id, reason)

    def snapshot(self):
        with self._connect() as db:
            budget = self._load(db)
        return dict(spent_usd=str(budget.spent), reserved_usd=str(budget.reserved),
                    calls=budget.calls, halted=budget.halted,
                    entries=json.loads(self._encode(budget))['entries'])
