"""Small-sample metrics with explicit denominators and score ties."""
import random


def detection_metrics(labels, scores, threshold=0.5):
    if len(labels) != len(scores):
        raise ValueError("labels and scores must align")
    pairs = [(bool(y), p) for y, p in zip(labels, scores) if p is not None]
    if any(not 0 <= p <= 1 for _, p in pairs):
        raise ValueError("probability score outside [0,1]")
    positives = sum(y for y, _ in pairs)
    negatives = len(pairs) - positives
    tp = sum(y and p >= threshold for y, p in pairs)
    fp = sum(not y and p >= threshold for y, p in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positives if positives else None
    f1 = 2 * precision * recall / (precision + recall) if recall and precision else 0.0
    if not pairs:
        precision = f1 = None
    elif recall is None:
        f1 = None
    pos = [p for y, p in pairs if y]
    neg = [p for y, p in pairs if not y]
    auc = (sum(1 if a > b else 0.5 if a == b else 0 for a in pos for b in neg)
           / (positives * negatives) if positives and negatives else None)
    ap, previous_recall = 0.0, 0.0
    for score in sorted({p for _, p in pairs}, reverse=True):
        selected = [(y, p) for y, p in pairs if p >= score]
        group_tp = sum(y for y, _ in selected)
        current_recall = group_tp / positives if positives else 0.0
        ap += (current_recall - previous_recall) * group_tp / len(selected)
        previous_recall = current_recall
    bins = [[(y, p) for y, p in pairs if min(int(p * 10), 9) == i] for i in range(10)]
    ece = sum(len(b) / len(pairs) * abs(sum(y for y, _ in b) / len(b)
             - sum(p for _, p in b) / len(b)) for b in bins if b) if pairs else None
    return dict(auroc=auc, auprc=ap if positives else None, precision=precision,
        recall=recall, f1=f1, brier=sum((p - y)**2 for y, p in pairs) / len(pairs)
        if pairs else None, ece=ece, healthy_fpr=fp / negatives if negatives else None,
        observed_count=len(pairs), missing_count=len(labels) - len(pairs),
        positives=positives, negatives=negatives, tp=tp, fp=fp)


def paired_bootstrap(deltas, seed=20261012, samples=2000):
    if not deltas:
        return {"mean_delta": None, "ci95": None, "samples": 0}
    rng = random.Random(seed)
    draws = sorted(sum(rng.choice(deltas) for _ in deltas) / len(deltas)
                   for _ in range(samples))
    return {"mean_delta": sum(deltas) / len(deltas),
        "ci95": [draws[int(0.025 * (samples - 1))], draws[int(0.975 * (samples - 1))]],
        "samples": samples, "interpretation": "descriptive controlled-dev only"}


def summarize(queries, epsilon=0.02, threshold=0.5):
    healthy = [q for q in queries if q["family"] is None]
    failing = [q for q in queries if q["family"] is not None]
    regressions = [q["query"] for q in healthy if any(
        q["after"][m] < q["before"][m] - epsilon
        for m in ("ndcg", "recall", "precision5"))]
    submitted = [q for q in queries if q["submissions"]]
    rejected = [q for q in queries if any(t["reason"] == "rejected" for t in q["trace"])]
    recovered = sum(q["accepted"] for q in failing)
    mean = lambda subset, when, metric: (sum(q[when][metric] for q in subset) / len(subset)
                                        if subset else None)
    return dict(query_count=len(queries), healthy_count=len(healthy), failing_count=len(failing),
        recovered_count=recovered, failure_recovery_rate=recovered / len(failing) if failing else None,
        failing_ndcg_before=mean(failing, "before", "ndcg"),
        failing_ndcg_after=mean(failing, "after", "ndcg"),
        failing_recall_after=mean(failing, "after", "recall"),
        failing_precision5_after=mean(failing, "after", "precision5"),
        healthy_regressions=regressions, healthy_regression_count=len(regressions),
        healthy_regression_rate=len(regressions) / len(healthy) if healthy else None,
        healthy_interventions=sum(q["intervened"] for q in healthy),
        unnecessary_action_rate=sum(q["intervened"] for q in healthy) / len(healthy)
        if healthy else None,
        submissions=sum(q["submissions"] for q in queries),
        mean_submissions=sum(q["submissions"] for q in queries) / len(queries) if queries else None,
        first_pass_acceptance=sum(q["accepted"] and q["submissions"] == 1 for q in submitted)
        / len(submitted) if submitted else None,
        submitted_query_count=len(submitted), rejected_query_count=len(rejected),
        recovery_after_rejection=sum(q["accepted"] for q in rejected) / len(rejected)
        if rejected else None,
        detection=detection_metrics([q["family"] is not None for q in queries],
            [q["detection"]["failure_probability"] for q in queries], threshold))
