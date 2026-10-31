"""Dev-only configuration freeze. No learned detector is trained in Phase 1."""
from searchclinic.research.splits import validate_splits, digest


def freeze_config(rows, config):
    records = validate_splits(rows)
    if not records or any(r.split != "dev" for r in records):
        raise ValueError("threshold/lambda selection requires dev-only data")
    return {"config": config, "split_hash": digest([r.model_dump() for r in records]),
            "config_hash": digest(config), "selection_split": "dev"}
