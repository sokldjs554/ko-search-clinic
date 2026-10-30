"""An uncalibrated rule score, independent of qrels and family labels."""
from searchclinic.research.models import Detection, PolicyObservation


DEFAULT_CONFIG = dict(version="rule-v1", threshold=0.5, coverage_threshold=0.5,
    margin_threshold=0.1, zero_score=0.95, coverage_score=0.8,
    margin_score=0.6, healthy_score=0.1)


class RuleDetector:
    def __init__(self, config=None):
        self.config = dict(DEFAULT_CONFIG if config is None else config)
        self.threshold = self.config["threshold"]

    def detect(self, observation: PolicyObservation) -> Detection:
        if type(observation) is not PolicyObservation:
            raise TypeError("detector requires label-free policy_view")
        c, o = self.config, observation
        reasons, scores = [], []
        if o.result_count is None:
            return Detection(failure_reason_codes=("missing_result_count",))
        if o.result_count > 0 and o.lexical_coverage is None and o.score_margin is None:
            return Detection(failure_reason_codes=("missing_quality_signals",))
        if o.result_count == 0:
            reasons.append("zero_results")
            scores.append(c["zero_score"])
        if o.lexical_coverage is not None and o.lexical_coverage < c["coverage_threshold"]:
            reasons.append("low_lexical_coverage")
            scores.append(c["coverage_score"])
        if o.score_margin is not None and o.score_margin < c["margin_threshold"]:
            reasons.append("low_score_margin")
            scores.append(c["margin_score"])
        score = max(scores) if scores else c["healthy_score"]
        return Detection(failure_probability=score, predicted_failure=score >= self.threshold,
                         failure_reason_codes=tuple(reasons))
