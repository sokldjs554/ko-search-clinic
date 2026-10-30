# Independent repair comparison implementation plan

> Use superpowers:executing-plans for inline implementation with tests first.

**Goal:** Prepare a label-isolated, same-input RulesPlus/LLM comparison without paid calls.
**Architecture:** A public observation builder sends strict JSON to a separate candidate worker. All arm candidates are sealed before a different evaluator process opens private labels. Existing Phase 0–1 modules and artifacts remain unchanged.
**Spec:** `PHASE2_NARROW_PLAN.md` and the user's 2026-10-12 Konkuk-only instructions.

## Constraints and review focus

- No paid API, external communication, main merge, UI or application documents in Git.
- The 36 public dev queries remain dev; new source-grounded authored queries are not natural user logs.
- Same context, schema, ordered maximum three candidates and fixed expected action cost for both arms.
- No final scores, qrels, family labels or retry feedback to generators.
- Wrong targets, forged spans, extra fields, duplicate/missing queries, changed seals and mixed provenance must fail closed.
- Budget missing usage, overshoot and transport failure stop without retry. This turn supplies an offline guard, not a live API client.
- Semantic/template leakage needs explicit review; lexical checks alone cannot certify independence.

## Tasks

1. Freeze `artifacts/research/phase2/protocol.json` in Git before new data outcomes. Preserve all older files.
2. Write/run failing `tests/test_phase2_boundary.py`; implement `phase2/contracts.py`, `generation.py`, `worker.py` for strict contexts, RulesPlus, process isolation, immutable candidate seals and no-feedback generation.
3. Write/run failing `tests/test_phase2_evaluation.py`; implement separate `evaluator.py` for complete label coverage, evidenced typed patches, unchanged full-set gate, costs, negative cases and group comparison. Only synthetic fixtures are scored before paid approval.
4. Write/run failing `tests/test_phase2_budget_data.py`; implement `budget.py` (no transport) and `data.py` overlap checks that expose unresolved semantic review.
5. Collect a small private corpus, source URLs/revisions/licenses, authored queries and separately held labels. Hash and audit without final scoring; independent human review remains required.
6. Implement explicit `python -m searchclinic.research.phase2` commands; exercise free preparation with private source data, whole suite and legacy quality checks. Report exact source/artifact hashes and pending real LLM comparison.

Official application facts and applicant documents are managed outside this repository.
