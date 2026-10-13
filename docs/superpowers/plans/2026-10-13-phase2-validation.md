# Phase 2 live-comparison validation plan

User specification: 2026-10-13 conversation. Preserve main/PR #1 and the original
pilot's 2 detector triggers / 0 valid RulesPlus candidates. No paid call without
separate approval. Do not change admissions documents or existing research results.

## Task 1: recover evidence and acquire a separate external pilot
- Check current branch, dirty state, artifacts and run existing tests.
- Original private pilot is unavailable in this checkout; do not reconstruct it.
- Before inspecting retrieval outcomes, fix the new selection: MIRACL Korean dev,
  first 12 topics in upstream file order, all passages judged for those topics.
  No outcome-dependent replacement, no query editing, no fabricated negatives.
- Pin upstream commits, byte hashes and retain positive AND negative judgments.
- Audit overlap with controlled-v1/dev, shared articles and unjudged pairs.
- Native-speaker upstream annotations are evidence of external labeling; a local
  machine audit is not a new independent human review. Do not mark review complete
  unless the required evidence exists. Corpus subsampling is a major limitation.

## Task 2: paid execution safety, tests before implementation
- Add a durable reservation journal to existing CallBudget; keep failed/ambiguous
  calls reserved and disallow duplicate/retry and concurrent execution.
- Freeze request bytes, model, pricing, context/label commitments and source SHA.
- Add transport only after the data/approval preconditions can be concretely met.
- Preserve generator/evaluator isolation and the existing paid-evaluation guard
  until approved execution evidence is available. No automatic model fallback.
- Test approval denial, crash recovery, cost caps, duplicate calls and seal changes.

## Task 3: report verified scope and next gate
- Run focused tests then the full existing default suite and baseline quality gate.
- Preserve test logs, hashes, protocol, source SHA and exact reproduction commands.
- Report local vs remote CI separately; no completion claim for unexecuted LLM work.
- Write docs/research/PHASE2_FINAL_REPORT.md with all nine requested sections.
- Provide official current model/pricing, bounded cost and review/access status.

## Review focus
Selection before outcomes; unjudged relevance vs negatives; human vs AI review;
crash/double-spend; no secrets in artifacts; no unsupported model-access claim;
no final-evaluation verdict supplied to generators. Generalization is withheld.

## Progress and rulings
- Base: 564a664ae533dba65935211f4534cdaf7eda4643; new branch
  feat/phase2-llm-validation-20261013. Main and PR #1 unchanged.
- Baseline: pytest -q -rs -> 394 passed, 2 skipped (optional PostgreSQL/scale).
- Ruling: source private pilot not recoverable here; a separately named external
  pilot avoids falsely claiming reconstruction. Its results must never overwrite
  the original pilot or be pooled with Legacy Claude results.
- Pre-flight: data review is a prerequisite for live execution. Missing independent
  review must block execution rather than be papered over with a status string.

- Task 1: source selection/extraction complete; semantic review blocked. Both AI reviews found material qrels conflicts; upstream labels unchanged. No retrieval outcomes inspected.
- Task 2: durable budget and deterministic extractor implemented. RED import failures then 15 focused tests GREEN. Full suite exposed positional rb-mode portability guard; changed to keyword mode, 22 focused portability/data/budget tests GREEN.
- Ruling: defer paid transport/data-specific final evaluator wiring until a usable reviewed label set exists. Otherwise engineering would create the impression that only paid approval remains; cost is an additional implementation step before actual experiment.
- Final review: fresh reviewer found no Critical/Important changed-code defect in documented string-ID offline scope; confirmed material data blockers. Review in docs/research/PHASE2_DATA_AND_CODE_REVIEW.md.
- Final: minor (deferred): standalone durable budget accepts non-string query IDs; current Context validates strings. Reject non-string IDs before external standalone paid integration.
