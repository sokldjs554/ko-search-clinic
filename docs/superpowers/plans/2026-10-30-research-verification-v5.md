# Research verification v5 implementation plan

> Execution: implement and verify in the existing repository, as requested. Independent audit is delegated under dispatching-parallel-agents; changes are integrated and reviewed before publication.

Goal: repair reproducibility and provide an auditable, label-free semantic selection experiment without inventing superiority.

Architecture: retain historical experiment records, integrate reusable Phase 0–2 and RAG modules onto current main, add a separately versioned v5 pipeline. Candidate/judge decisions are frozen before scoring. A quality gate with development qrels is not a final-evaluation selector.

Spec: user's uploaded 2026-10-30 request (all eleven sections).

Constraints: no paid calls without separate approval; no access to encrypted data without a key; no independent-review or blind-test claims without actual evidence; keep v3/v4 immutable; no merging existing draft PRs.

## Tasks

- [x] Audit all remote branch heads, workflow records, public v4 runtime and saved development candidates. Record inaccessible data and distinguish source analysis from raw-result reproduction.
- [x] Reproduce main failure, reuse PR2 Kiwi 0.24.1/model 0.24.0/cong-global fix, retain baseline file. Integrate additive PR1/Phase2 and RAG code with source provenance, excluding paid workflows and transport archives.
- [x] Add failing mean-loss gate test; separate mean preservation tolerance (1e-12 numerical tolerance) from per-query epsilon (0.02); retain target gain 0.05; test acceptance, rejection and session isolation.
- [x] Add strict semantic verdict schema, same-candidate pair/context/rubric prompt conditions, exact source citations, label-free selection and per-query independent application. Test target/scope/category violations, missing/invalid verdicts and no final-qrels input.
- [x] Add offline evaluation: complete coverage, split/document/concept leakage checks, ambiguity/reviewer metadata, hashes/seals, diagnostic oracle, matched-count random arms, ablations, paired cluster bootstrap, useful rejection and cost/latency accounting. Test hand-derived metrics and tampering.
- [x] Run available saved development candidates through the new offline diagnostic path. Label all results retrospective development; leave fresh blind evaluation unexecuted if no qualifying data exists.
- [x] Pin CI environment, run full tests/baseline, preserve output. Update README, research report and existing demo links with exact evidence and limitations. Review, commit, open new draft PR and verify Linux/Windows Actions.

## Review focus

Missing rows must fail rather than disappear; score/rationale/label leakage into selectors must be rejected; judge citations must bind to the exact query/candidate/context; random arms must match application counts; bootstrap units must respect concept groups; RAG replay remains distinct from retrieval superiority.

## Decisions and progress

- The user's explicit request to proceed through implementation supersedes interactive design checkpoints. Native execution plus an independent source audit is used.
- New branch `feat/research-verification-v5-20261030` starts at main `f3ca14a68329cd3ef95e5b362f6224d35fe397ca`; fresh clone is isolated from user work.
- v4 public runtime archive SHA256 verified before extraction. Encrypted output has not been decrypted. No API generation has occurred.

- Implemented: additive branch integration, Kiwi fix, full-precision mean gate, strict semantic conditions, isolated sealed application, scoring/statistics/split audits, saved development replay, real offline preparation and no-verdict hold check.
- Independent AI code review found generation-error omission and rounded gate metrics; both reproduced RED then fixed GREEN. No deferred minor findings.
- Limits retained: no decryption, fresh independent relevance judgments, real LLM semantic trials or RFL training. Paid API and credential decisions remain pending.
- Local full suite 561 passed, 2 skipped; baseline preserved; Chromium 36 queries,3 arms,1440/320/390px,0 page errors. Native API-live transport was not added while credential decision is pending.

- Published integration commit1055e2d and CI-import correction fd073c5 in Draft PR #3. Initial remote Ubuntu/Windows failures were test script discovery under console pytest; local reproduction and 561-pass console run confirm the fix. Remote rerun41043768505 passed Ubuntu/Windows (561 passed,2 skipped each) and baseline.
- Automatic approval review rejected newly generated private labels and detailed development outputs for public publication. They remain local/ignored; the public demo displays aggregates and local full-detail mode remains available.
