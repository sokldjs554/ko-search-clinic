# Frozen v5 comparison and evaluation

This is a **free offline analysis pipeline**, not evidence that a live LLM
experiment has occurred. It makes no provider calls. Paid transport requires
separate approval. Mock transport proves orchestration only. The original 15
saved candidates are **historical scripted submissions**, selected through
historical diagnosis and outcome-dependent stopping; they are not GPT output.

## Three separate invocations

Run from the repository root with the project Python environment:

```bash
python scripts/compare_v5_conditions.py freeze \
  --bundle work/v5-followup/development/candidates.json \
  --candidate-source historical_scripted \
  --out work/comparison/protocol.json

python scripts/compare_v5_conditions.py assemble \
  --bundle work/v5-followup/development/candidates.json \
  --protocol work/comparison/protocol.json \
  --transport-dir work/v5-mocked-transport-final \
  --protected-root work/v5-followup/development/private \
  --out work/comparison/assembly.json

python scripts/compare_v5_conditions.py score \
  --assembly work/comparison/assembly.json \
  --labels work/v5-followup/development/private/labels.json \
  --out work/comparison/private/report.json
```

All outputs use exclusive creation beneath ignored `work/`, including resolved symlink checks. Preserve existing artifacts and choose a
new output directory for another run. Keep reports local: they contain detailed
per-query retrieval diagnostics and identifiers. They are not public summaries.

`assemble` installs the existing declared-path audit hook before imports or
input reads. Supply **every relevant private label directory** with repeated
`--protected-root` options. Application and RulesPlus generation execute without
label arguments or evaluator imports. Only the later `score` invocation reads
labels. This is a trusted-code boundary, not an operating-system sandbox or proof
that the researcher has never seen the data. The library convenience function
`compare_conditions` runs in one process and explicitly does not claim isolation.

## Input contracts and reuse

* `freeze_analysis_protocol(bundle, candidate_source=..., study_scope=...,
  repeats=2, phase="development")` returns a SHA256-sealed prospective protocol.
  Candidate source is `historical_scripted`, `gpt_generated`, or `mock`.
* `assemble_comparison(bundle, trials, protocol=..., attestations=None,
  transport_summary=None, transport_evidence=None)` returns a sealed label-free assembly. It reuses
  `pipeline.apply_candidates` and `pipeline.diagnostic_candidates` for all real
  retrieval execution. Each semantic condition/repeat requires exactly one row:
  `{"condition":"pair","repeat":1,"input_hash":"...","verdicts":{...}}`.
  Verdict maps cover every query and exactly every original candidate position;
  explicit `null` represents a missing verdict. Missing trials, shortened lists,
  duplicate repeats and changed candidate hashes are errors.
* Instead of `--transport-dir`, `assemble --trials trials.json` accepts that
  complete JSON list. Transport folders must contain a verified sealed
  `plan.json`, matching `summary.json`, and every attempted request, reservation,
  raw response and outcome. Verdicts are re-parsed from raw bodies and must match
  `verdicts-{pair|context|rubric}-repeat-{1|2}.json` exports. Completed and stopped
  runs are accepted for development with full missing-call denominators; final
  evaluation requires complete provider evidence. More repeats work
  when frozen in advance. Saved verdicts without provider provenance remain
  explicitly unverified.
* `score_comparison(assembly, queries, qrels, human_semantics=None, ...)` reuses
  `evaluation.score_runs`, `oracle_analysis`, and `matched_random_selection`.
  Labels contain exactly `queries` and `qrels`. Queries need `query_id`,
  `stratum` (`healthy` or `failure`), and `concept_id`. Qrels must cover every
  query with complete nonnegative integer judgments. A missing annotation is
  not an explicit all-nonrelevant query. The KLUE source proxy annotations are
  incomplete and **must not be converted automatically into final qrels**.
* Optional private human semantic labels map query ID to candidate index string
  to `true`, `false`, or `null`. They judge the complete candidate's meaning
  preservation independently from retrieval relevance. They never enter
  selection. Qrels cannot supply semantic correctness labels.

Both the prospective protocol and application assembly bind implementation
hashes. Changing analysis/application/generator sources requires a new protocol
and assembly. Hashes detect changes; they do not certify temporal preregistration
or the truth of provenance statements.

## Comparisons and scope

Pair, Context, and Rubric select from the **same frozen ordered candidates**.
The `first_valid` arm selects the first structurally and literally supported
candidate without semantic verification. It is called a GPT basic selector
baseline only when its actual candidate source is GPT generation. NoRepair
retains immutable base retrieval. Every patch starts from that same pristine
engine and affects its target query; the study does not simulate cumulative
global configuration deployment.

RulesPlus is a **separate generator baseline**. The pipeline reuses existing
`phase2.generation.build_context` and `generate_rules`, then applies its first
valid candidate without a qrels gate. It reconstructs label-free retrieval
context from the corpus; it does not use historical candidate terms as a source
of generator evidence. Its existing detection policy and up-to-three-candidate
ladder remain intact. A RulesPlus generation error holds the entire query.

`selection_only` conditions on supplied candidates and cannot estimate a new
generator's capability. `full_system` requires GPT candidate provenance and
exactly identical fresh public generator contexts for GPT and RulesPlus. Merely
judging historical scripted candidates with GPT does not make a full-system
study. Even in selection-only reports, RulesPlus is identified separately.

The report includes:

* Apply/hold counts; malformed, missing and rejected judgments; invalid
  candidates; application/generation errors. `generation_missing_count` counts
  queries with no candidates, including explicit abstention; the separate
  `generation_abstention_count` counts empty lists without generation errors.
* Retrospective candidate-oracle utility, useful-candidate false holds, harmful
  accepted repairs, and normal-query regressions. A false hold requires a held
  query with a replayable candidate that improves nDCG@10. Harmful acceptance
  means any metric decreases by more than numerical roundoff. Oracle usefulness
  is conditional on the observed candidate set and is not semantic truth.
* Semantic correctness remains `UNKNOWN` wherever human semantic judgments are
  unavailable. High model confidence, literal evidence and better retrieval
  metrics do not make correctness known.
* Per-query paired metric differences and concept-cluster intervals; separate
  repeat variability and selection disagreement. Repeats are averaged within
  query before primary bootstrap, never counted as independent extra queries.
* Matched random selection with exactly the same application count as each
  semantic/first-valid run, over structurally replayable candidate queries.
  Seeds and choices are retained. When every eligible query is selected and
  each has one candidate, this control is necessarily deterministic.
* Provider transport costs/latency as recorded separately from offline
  application latency. Missing provider cost information stays missing. A mock
  reservation ceiling is not a payment or real model performance measurement.
* Fixed confidence thresholds `0, .5, .8, .9, 1` as a diagnostic over the same
  saved judgments. No threshold is recommended as optimal; confidence is not a
  calibrated probability. Thresholds never alter the frozen primary decision.

## Prospective final criteria and blocking conditions

Before final outcomes, freeze Rubric as the primary condition, overall mean
nDCG@10 as the primary metric, and NoRepair and RulesPlus as the two comparators.
Require at least **+.01 against both**, with the **lower bound of each 97.5%
two-sided paired concept-cluster interval at least +.01**. The two intervals use
Bonferroni correction for familywise alpha .05. This is stricter than requiring
only a positive corrected lower bound and a +.01 point estimate.

Also require **zero normal-query regressions** in every primary repeat on every
reported metric (loss greater than `1e-12`), not merely a safe average. The older
evaluator's descriptive `.02` practical regression listing remains in its score
report and is not the primary safety criterion. Final sampling is frozen at
2,000 bootstrap draws, 100 matched-random repeats, seed 20261030. Development
overrides are recorded explicitly; final overrides are rejected. Exploratory
Pair/Context/Rubric differences have descriptive 95% intervals and cannot be
substituted as primary results after looking at outcomes.

Final assembly is blocked without a sealed attestation bound to `input_hash`
and `protocol_hash`, with every following value literally `true`:

```json
{
  "eligibility_verified": true,
  "human_review_complete": true,
  "exposure_audit_complete": true,
  "independent_concepts_verified": true,
  "frozen_before_final_outcomes": true,
  "candidate_generation_verified": true
}
```

These attestations must be supported by the actual reviewed evidence; writing
`true` cannot repair missing exposure lists, sparse labels or a known leak.
Actual bound raw provider evidence and GPT candidate provenance are additionally
required. A summary claiming provider calls cannot substitute for raw evidence.
Saved transcripts establish internal consistency, not provider-signed authenticity. Final scoring requires complete human semantic candidate judgments,
both normal/failure populations, and at least two independent concept groups.
The currently prepared independent proxy data do not satisfy these conditions.
Do not claim a final result, superiority, or an optimal threshold from the free
mocked run or historical development replay.
