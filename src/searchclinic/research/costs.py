"""Measured search/reindex counts and nullable external model usage."""
import math
from dataclasses import dataclass, fields

from searchclinic.index.engine import SearchEngine


@dataclass(frozen=True)
class CostRecord:
    search_calls: int = 0
    reindexes: int = 0
    model_calls: int | None = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    latency_ms: float | None = 0.0
    api_cost_usd: float | None = 0.0

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"invalid cost: {f.name}")
            if f.name not in ("latency_ms", "api_cost_usd") and value is not None:
                if type(value) is not int:
                    raise ValueError(f"cost count must be an integer: {f.name}")


def aggregate_costs(costs: list[CostRecord]) -> CostRecord:
    values = {}
    for f in fields(CostRecord):
        parts = [getattr(c, f.name) for c in costs]
        values[f.name] = None if any(x is None for x in parts) else sum(parts)
    return CostRecord(**values)


DEFAULT_WEIGHTS = dict(regression=1.0, model_calls=0.01, tokens=0.000001,
                       latency_ms=0.00001, unnecessary_actions=0.005)


def utility(quality_gain: float, healthy_regression: float, cost: CostRecord,
            unnecessary_actions: int = 1, weights: dict | None = None) -> float | None:
    w = weights if weights is not None else DEFAULT_WEIGHTS
    if any(getattr(cost, x) is None for x in
           ("model_calls", "input_tokens", "output_tokens", "latency_ms", "api_cost_usd")):
        return None
    return (quality_gain - w["regression"] * healthy_regression
            - w["model_calls"] * cost.model_calls
            - w["tokens"] * (cost.input_tokens + cost.output_tokens)
            - w["latency_ms"] * cost.latency_ms
            - w["unnecessary_actions"] * unnecessary_actions)


@dataclass
class SearchMeter:
    search_calls: int = 0
    reindexes: int = 0


class MeasuredEngine(SearchEngine):
    def __init__(self, docs, config=None, meter=None):
        self.meter = meter if meter is not None else SearchMeter()
        super().__init__(docs, config)
        self.meter.reindexes += 1

    def search(self, query, k=10):
        self.meter.search_calls += 1
        return super().search(query, k)

    def with_config(self, config):
        return MeasuredEngine(list(self.docs.values()), config, self.meter)
