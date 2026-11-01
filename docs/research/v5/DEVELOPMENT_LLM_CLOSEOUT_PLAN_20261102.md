# Development LLM comparison implementation plan

> Execute inline with `superpowers:executing-plans`; retain private execution evidence.

**Goal:** Run a new GPT generator and the existing three semantic selectors on the existing 36 development queries after separate paid approval.

**Architecture:** Reuse phase2 public retrieval contexts and prescription validation, v5 transport reservations/raw evidence, comparison assembly and separate scoring. Add a sealed parent plan authorizing a bounded generation stage and a deterministic judge stage; never reuse the consumed 90-call approval.

**Scope:** The user's 2026-11-02 instruction stops additional human-review assignments. The 51 resolved relevance pairs concern one KLUE query and remain annotation-pilot evidence. This comparison is development-only, not an independent final evaluation. Existing v3/v4 evidence, human submissions and failed runs remain unchanged.

## Fixed design

- Model: `gpt-4.1-mini-2025-04-14`, subject to a fresh GET-only access check.
- All 36 development queries, one generator call each, at most three ordered prescriptions; no outcome-dependent query/candidate selection.
- Same generated candidates for first-valid GPT, Pair, Context, Rubric and Matched Random; RulesPlus uses the same fresh public contexts. No Repair included.
- Two judge repetitions per candidate per condition; generator variability is not estimated from a single generator sample.
- Generator: input at most 12,000 conservative tokens including wire schema/framing, output 1,500. Judges: input 12,000/output 2,000. Oversize inputs are withheld, no hidden truncation or retry.
- At most 36 generator + 648 judge calls = 684; input 8,208,000/output 1,350,000 tokens in total. At $0.40/$1.60 per million, maximum usage cost $5.4432 (not a billing receipt, excluding tax).
- Preserve `comparison.PRIMARY`: Rubric, +0.01 minimum gain over both No Repair and RulesPlus, corrected 97.5% intervals, zero healthy-query metric regressions; 2,000 cluster bootstraps and 100 matched random repetitions. Development results cannot certify population superiority even if numerical criteria pass.
- Confidence 0.8 stays an uncalibrated engineering default. Previously developed grounding/zero-hit rules may be reported as explicitly secondary analyses; primary raw results remain intact.
- No new human semantic-accuracy claim for newly generated candidates without new human labels. Retrieval utility/oracle misses remain measurable with existing private development qrels.

## Tasks and checks

1. Add `research_v5/generation.py`: sealed parent/generator plans, structured parsing, raw-response reconstruction, exact approval and deterministic stage handoff. Test changed approval, credential redaction, failed/partial generation, empty output, bad sibling, no retry, and budget bounds before implementation.
2. Extend `transport.py` through explicit new plan profiles; preserve old default plans and their hashes. Reuse durable claims/reservations and response parsing. Verify old transport/evidence suites plus new empty/large profiles.
3. Add `scripts/run_v5_generated.py` and a separately gated encrypted workflow. Prepare fresh contexts without private qrels, enforce declared label paths, keep the old paid workflow untouched. Test mock generation → judge → raw evidence → full-system assembly and separate scoring.
4. Run full pytest and Ubuntu/Windows CI; refresh free model access, verify official price, publish aggregate proposal/hashes only. Request exact paid approval only when these checks are reviewable; do not execute paid generation before it.

## Review focus

- All candidates withheld must still retain all query denominators.
- Partial generation must not silently authorize judging or a retry.
- An invalid candidate must not suppress a valid sibling or lose original provenance.
- Parent/child budgets, frozen code and predeclared analysis must agree.
- Remote artifacts must contain ciphertext only, including on failure.
