"""Patch exports; importing the IR alone must not load the evaluation gate."""
from importlib import import_module

__all__ = [
    "Prescription", "PATCH_KINDS", "run_gate", "GateVerdict", "RegressionRecord",
    "MIN_TARGET_GAIN", "EPSILON", "to_es_settings", "render_es_json",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = ("ir" if name in {"Prescription", "PATCH_KINDS"} else
              "es_render" if name in {"to_es_settings", "render_es_json"} else "gate")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
