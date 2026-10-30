# Phase 2 free execution status — 2026-10-12

Implementation source: `7e3f8609a71d38c6d10cb78f82981806f07dde7b`.
Source hash: `ec23db9e3eb4cdf6c6ad129a835e8bd7e43aa3537b5faa1aaa7277054bd0d194`.
Pre-outcome protocol: `921ce4b381a4848ee6f897bf297a0233589644eb`.
Starting PR#1 head: `3238d58a69a8bc7881f971138f4c1278e46dc402`.

Existing222 tracked files are byte-identical to the starting head. The separate
`feat/phase2-independent-evaluation` branch was pushed; PR#1 remains draft,
unmerged at its original head. Main remains `80ea3bcf…`. Application documents,
sealed labels, source-data copies and candidate payloads are outside Git.

## Actual free execution

`prepare` processed8 source adaptations and12 authored stimuli. Public input
manifest was frozen before generation; RulesPlus candidates were generated
in separate workers; LLM requests were prepared but not sent. Shared preparation
used24 search calls and1 reindex. Only2 stimuli triggered the frozen detector.
That count is a diagnostic signal, not a verified failure count. Model calls,
tokens and API cost are0; no wall-clock speed comparison is made.

Candidate seal `10c8872cea81c71ecebec2b7857a6a8a251c2b9464e47740dfd95b96c9b92d17`.
Dataset hash `de267f94139a1e375dc6cca4e29b63e940c6351b7680d8f63f769a92c5cfb48e`.
The private data remain provisional: six concept groups, template overlap,
unreviewed intended strata and incomplete independent qrels review. Thus no
certified independent evaluation or final arm scoring has happened.

| Arm | Candidate status | Final quality/regression score |
|---|---|---|
| no repair | Reference evaluator implemented | not run |
| RulesPlus | Private ordered candidates prepared | not run |
| actual LLM | Request schema prepared; no provider transport/calls | not run |

Synthetic unit fixtures verify positive and negative gate outcomes and process
boundaries. They are not experimental evidence of LLM improvements.

## Tests and review

- New Phase2 suite:41 passed. Reviewed corpus mutation, fake provenance and
  unknown-field weaknesses were reproduced and fixed with new tests. The
  follow-up reviewer independently ran41 tests and confirmed the fixes.
- Default full suite:413 passed,1 skipped,2 slow tests deselected (71.71s).
- The two slow cases separately:1 passed,1 skipped;19 other scale cases
  deselected in that targeted run (41.97s).
- Combined unique full coverage:414 passed,2 skipped. Skips: `psycopg2`
  PostgreSQL module and missing `pyspark` slow case.
- Post-commit evaluator/provenance suite:15 passed (4.27s).
- Existing quality baseline: success, mean nDCG0.5839. This is the existing
  public development baseline, not the independent pilot.

Default/slow full runs occurred on HEAD921ce4b with uncommitted new code;
that source tree was committed unchanged as7e3f860. The post-commit suite and
private preparation record exact7e3f860 and clean source status. These facts
are separate in `artifacts/research/phase2/free-preparation-status.json`.

The first restricted-sandbox full run hung at the legacy REST TestClient.
A20s isolated reproduction timed out. The same test passed with sandbox
network permission (2.51s), then the full suite completed under that condition.
No production or legacy test changes were made to bypass the hang.

## Remote CI — blocked, no retry

Attempted once:

```text
gh workflow run ci.yml --repo sokldjs554/ko-search-clinic --ref feat/phase2-independent-evaluation
Get "https://api.github.com/repos/sokldjs554/ko-search-clinic/actions/workflows/ci.yml": Forbidden
```

Exit1; no new run URL, job result or checkout SHA exists. No repeated request
or alternate authorization path was used. Feature pushes alone do not trigger
the unchanged main-only push workflow.

Existing Phase0–1 CI [38213317359](https://github.com/sokldjs554/ko-search-clinic/actions/runs/38213317359)
still shows Ubuntu/Windows353 passed2 skipped and quality success at checkout
`fd6cf1955bca25843bf85fb662acb800531e49a0`, head3238d58. This is not validation
of the new Phase2 branch.

## Remaining research questions and prerequisites

Resolve template/semantic overlap and independently review exhaustive qrels
before calling the pilot held-out data. The current adaptation/query authoring
may produce no real failure, and detector misses may prevent useful LLM
comparisons; neither should be remedied by post-outcome query selection.
Can evidence-grounded semantic repair help once genuinely independent failures
exist? Can it avoid healthy regressions under the same ordered candidate budget?
The current small authored dataset cannot establish generalization.

After data review, obtain separate model/budget approval, implement and test
the provider transport and approved execution manifest, freeze both real arms
before scoring, and verify new remote CI when authorized access is available.
Prices/call ceilings are proposals in `PHASE2_MODEL_BUDGET.md`, not actual spend.
