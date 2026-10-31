"""Use the unchanged v1 gate with explicit evidence, budget and feedback guards."""
from dataclasses import asdict

from searchclinic.analysis.jamo import jamo_similarity
from searchclinic.corpus import load_evalset
from searchclinic.patch.gate import run_gate, MIN_TARGET_GAIN, EPSILON
from searchclinic.research.actions import ActionKind, prescription_terms
from searchclinic.research.policy import Budget


class GateAdapter:
    def __init__(self, engine, evalset, budget=None, min_gain=0.05, epsilon=0.02):
        if evalset != load_evalset():
            raise ValueError("full v1 evalset, including every healthy query, is required")
        self.engine, self.evalset = engine, evalset
        self.budget = budget or Budget()
        if not (0 <= self.budget.max_submits <= 3 and 0 <= self.budget.max_actions <= 3):
            raise ValueError("budget must remain within v1 maximum 3")
        self.min_gain, self.epsilon = min_gain, epsilon
        if not self._valid_contract():
            raise ValueError("v1 gate contract cannot be relaxed or nonfinite")
        self.accepted, self.trace = [], []
        self.target, self.feedback = None, None

    def _valid_contract(self):
        if self.min_gain != MIN_TARGET_GAIN or self.epsilon != EPSILON:
            return False
        b = self.budget
        values = (b.max_actions, b.max_submits, b.used_actions, b.used_submits)
        return (all(type(v) is int and v >= 0 for v in values)
                and b.max_actions <= 3 and b.max_submits <= 3)

    def start_session(self, query):
        if query not in {q.query for q in self.evalset}:
            raise ValueError("unknown query outside evalset")
        self.target, self.feedback = query, None
        self.budget.used_actions = self.budget.used_submits = 0

    def _evidence_valid(self, candidate):
        rx = candidate.prescription
        if rx is None or not candidate.evidence:
            return False
        texts = set()
        for span in candidate.evidence:
            if span.source_type == "query":
                if span.source_id != rx.target_query:
                    return False
                source = rx.target_query
            else:
                doc = self.engine.docs.get(span.source_id)
                if doc is None:
                    return False
                source = doc.text
            if source[span.start:span.end] != span.text:
                return False
            texts.add(span.text.casefold())
        return {t.casefold() for t in prescription_terms(rx)} <= texts

    @staticmethod
    def _supported_relation(rx):
        # A conservative morphology baseline, not an independent semantic judge.
        compact = rx.target_query.replace(" ", "").casefold()
        if any(w.form.casefold() not in compact for w in rx.user_words):
            return False
        for group in rx.synonym_groups:
            canonical = group.terms[0]
            variants = [t for t in group.terms[1:] if t.casefold() in compact]
            if not variants or max(jamo_similarity(canonical, t) for t in variants) < 0.65:
                return False
        if any(not any(p.casefold() in compact for p in c.parts)
               for c in rx.compound_expansions):
            return False
        return True

    def submit(self, candidate):
        previous = self.feedback
        record = {"action": candidate.action.value, "accepted": False,
                  "previous_feedback": previous, "regressions": [],
                  "evidence_ids": [e.evidence_id for e in candidate.evidence],
                  "evidence": [e.model_dump() for e in candidate.evidence],
                  "prescription": candidate.prescription.model_dump()
                    if candidate.prescription is not None else None}

        def finish(reason, feedback=None):
            record.update(reason=reason, attempt=self.budget.used_submits,
                          feedback=feedback or reason)
            self.feedback = record["feedback"]
            self.trace.append(record)
            return record

        if not self._valid_contract():
            return finish("invalid_configuration")
        if candidate.action != ActionKind.TYPED_PATCH:
            return finish("unsupported_action")
        if self.budget.exhausted:
            return finish("budget_exhausted")
        rx = candidate.prescription
        if rx is None:
            return finish("invalid_prescription")
        if rx.target_query not in {q.query for q in self.evalset}:
            return finish("unknown_target")
        if self.target is not None and rx.target_query != self.target:
            return finish("target_mismatch")
        self.budget.used_actions += 1
        if not self._evidence_valid(candidate):
            return finish("invalid_evidence")
        if not self._supported_relation(rx):
            return finish("unsupported_relation")
        self.budget.used_submits += 1
        try:
            verdict, sandbox = run_gate(self.engine, self.evalset, rx,
                min_gain=self.min_gain, epsilon=self.epsilon)
        except Exception as exc:
            record["exception"] = {"type": type(exc).__name__, "message": str(exc)}
            return finish("gate_error")
        record.update(accepted=verdict.accepted, verdict=asdict(verdict),
                      regressions=[asdict(r) for r in verdict.regressions])
        if verdict.accepted:
            self.engine = sandbox
            self.accepted.append(record)
        return finish("accepted" if verdict.accepted else "rejected", verdict.feedback())
