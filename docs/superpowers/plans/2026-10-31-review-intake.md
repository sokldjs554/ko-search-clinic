# Independent review handoff and intake implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the existing blank review sheets into private, blinded handoffs and verifiable submissions without inventing human judgments.

**Architecture:** Reuse the existing semantic15 and KLUE200 preparation. A small offline module projects reviewer inputs, binds immutable templates, validates submitted CSVs, and reconciles two reviewers with explicit third-person adjudication. No selector or frozen experimental method changes.

**Tech Stack:** Python standard library, existing `pipeline.freeze/verify`, private `work/` CLI paths, pytest.

**Spec:** `docs/research/v5/HUMAN_REVIEW.md` and the user's continuing independent-evaluation request.

## Global constraints

- No additional paid calls, main merge, detailed publication, or messages to reviewers.
- Actual human judgments remain zero until real submissions arrive. Aliases are self-reported identities, not identity verification.
- Keep source preparations and raw experiment records immutable. New handoffs and receipts are write-once under ignored work/.
- Remove LLM judgments, source QA answers, retrieval scores/counts, and candidate diagnosis/reasoning from reviewer handoffs.
- Complete relevance judgments alone never certify exposure, concepts, candidate generation, or final evaluation readiness.
- Preserve missing and ambiguous judgments separately; no automatic zero conversion or exclusions.

## Approaches and decision

Existing CSV instructions alone are insufficient to prevent malformed/incomplete submissions from becoming labels. A new annotation service would add unnecessary operations. Extend the existing local CSV workflow with strict intake and sealed receipts. The user requested autonomous free continuation; reviewer assignment and decryption remain external inputs, not design-approval gates.

## Review focus

- BOM/CRLF CSV, duplicate rows/headers, foreign IDs and wrong splits must be handled explicitly.
- Blank grade versus genuine zero/false; partial submission versus ambiguous completed review.
- Self-reported reviewer identities cannot prove actual independence; never set final-ready from aliases alone.
- Provenance mismatches, changed frozen inputs and same-reviewer adjudication must fail.
- Constant-grade kappa has undefined denominator; do not fabricate perfect agreement.

### Task 1: Private handoff and strict submission intake

Files: `src/searchclinic/research_v5/review.py`, `scripts/review_v5.py`, `tests/test_v5_human_review.py`.
Interfaces: `prepare_handoff(source, kind, output)`, `validate_submission(packet_dir, submission, reviewer_id)`.

- [x] Write tests showing blinded projection, immutable hashes, blank progress, grade zero/false, invalid coverage/schema/identity/time, and source preservation.
- [x] Run tests RED, implement minimal module and CLI, run focused tests GREEN.
- [x] Build actual semantic/relevance handoffs from existing local sources and validate blank sheets; retain zero completed reviews.

### Task 2: Agreement and adjudication

Interfaces: `reconcile(review_a, review_b, adjudications=None)` returns sealed private report, queue and labels only when complete.

- [x] Test real grade agreement, weighted kappa, degeneracy, ambiguity/missing, provenance mismatch, distinct adjudicator and prohibited overrides.
- [x] RED→GREEN implementation; validate complete synthetic examples only in tests (never as research evidence).
- [x] Run actual blank reconciliation, preserve missing/ambiguous counts and final_evaluation_ready=false.

### Task 3: Verification and handoff

- [x] Review the new code in a fresh context; fix substantive findings with regression checks.
- [ ] Run full pytest, baseline, privacy scan, Ubuntu/Windows CI; publish code and aggregate readiness only to existing PR3.
- [ ] Update human instructions, README link and final-status; preserve 90-call findings and Draft status.
