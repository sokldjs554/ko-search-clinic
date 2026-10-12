"""Selective cost-aware rules. Quality labels are not accepted at this boundary."""
from dataclasses import dataclass

from searchclinic.research.actions import ActionKind, Candidate
from searchclinic.research.costs import utility


@dataclass
class Budget:
    max_actions: int = 3
    max_submits: int = 3
    used_actions: int = 0
    used_submits: int = 0

    @property
    def exhausted(self):
        return self.used_actions >= self.max_actions or self.used_submits >= self.max_submits


@dataclass(frozen=True)
class Decision:
    action: ActionKind
    reason: str
    candidate: Candidate | None = None
    utility: float | None = None


def select_action(detection, candidates, budget, weights=None, min_gain=0.05):
    if detection.predicted_failure is False:
        return Decision(ActionKind.NO_OP, "healthy_trace")
    if budget.exhausted:
        return Decision(ActionKind.ABSTAIN, "budget_exhausted")
    if detection.predicted_failure is None:
        return Decision(ActionKind.ABSTAIN, "insufficient_observation")
    available = [c for c in candidates if c.evidence]
    if not available:
        return Decision(ActionKind.ABSTAIN, "no_evidenced_candidate")
    scored = [(utility(detection.failure_probability * min_gain, 0, c.cost,
                       weights=weights), c) for c in available]
    scored = [(score, c) for score, c in scored if score is not None]
    if not scored:
        return Decision(ActionKind.ABSTAIN, "unknown_cost")
    score, candidate = max(scored, key=lambda x: x[0])
    if score <= 0:
        return Decision(ActionKind.ABSTAIN, "nonpositive_utility", utility=score)
    return Decision(candidate.action, "positive_utility", candidate, score)
