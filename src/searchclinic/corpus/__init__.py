"""Corpus exports, loaded on demand so public documents do not import labels."""
from importlib import import_module

__all__ = [
    "Document", "CATALOG", "load_catalog", "EvalQuery", "FAMILIES", "HEALTHY",
    "FAILING", "ZERO_RESULT_AT_BASELINE", "load_evalset", "healthy_queries",
    "failing_queries",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = "catalog" if name in {"Document", "CATALOG", "load_catalog"} else "evalset"
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
