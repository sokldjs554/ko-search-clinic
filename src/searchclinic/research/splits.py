"""Explicit metadata and cross-split leakage checks, not a fake held-out split."""
import hashlib
import json
import unicodedata
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def normalize_query(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class SplitRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    split: Literal["train", "dev", "test"]
    document_ids: list[str] = Field(min_length=1)
    template_id: str = Field(min_length=1)
    synonym_group_ids: list[str] = Field(min_length=1)


def validate_splits(rows, evalset=None, docs=None):
    records = [r if isinstance(r, SplitRow) else SplitRow(**r) for r in rows]
    seen_ids, seen_queries, ownership = set(), set(), {}
    for r in records:
        normalized = normalize_query(r.query)
        if r.query_id in seen_ids:
            raise ValueError("duplicate query_id")
        if normalized in seen_queries:
            raise ValueError("query leakage or duplicate normalized query")
        seen_ids.add(r.query_id)
        seen_queries.add(normalized)
        dimensions = {"doc": r.document_ids, "template": [r.template_id],
                      "group": r.synonym_group_ids}
        for dimension, values in dimensions.items():
            for value in values:
                if not value.strip():
                    raise ValueError("missing split metadata")
                key = (dimension, value)
                if key in ownership and ownership[key] != r.split:
                    raise ValueError(f"split {dimension} leakage: {value}")
                ownership[key] = r.split
    if evalset is not None and {r.query for r in records} != {q.query for q in evalset}:
        raise ValueError("evalset coverage mismatch")
    if docs is not None:
        ids = {d.doc_id for d in docs}
        if any(set(r.document_ids) - ids for r in records):
            raise ValueError("unknown document in manifest")
    return records


def prepare_manifest(evalset, docs, seed=20261012):
    rows = []
    for q in evalset:
        qid = "q-" + digest(normalize_query(q.query))[:16]
        # Document concepts are explicit evaluator metadata, never policy inputs.
        rows.append(SplitRow(query_id=qid, query=q.query, split="dev",
            document_ids=sorted(q.qrels), template_id="v1:" + qid,
            synonym_group_ids=["concept:" + d for d in sorted(q.qrels)]).model_dump())
    validate_splits(rows, evalset, docs)
    return dict(schema_version=1, dataset="controlled-v1", seed=seed,
        counts={"train": 0, "dev": len(rows), "test": 0}, heldout_status="not_collected",
        corpus_hash=digest([asdict(d) for d in docs]),
        evalset_hash=digest([asdict(q) for q in evalset]), split_hash=digest(rows), rows=rows)
