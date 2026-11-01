# Phase 2 free preparation and evaluation boundary

This work starts at `3238d58a69a8bc7881f971138f4c1278e46dc402`, uses the
separate branch `feat/phase2-independent-evaluation`, and keeps PR#1/head,
main, all v1/phase01-v1/phase01-v2 files and results unchanged. The protocol was
committed at `921ce4b381a4848ee6f897bf297a0233589644eb` before new data scores.
`PHASE2_NARROW_PLAN.md` remains the older plan, not a report of executed LLM work.

## Status and private data

Eight concise, attributed Korean Wikipedia adaptations, cross-checked with
NASA/NOAA/USGS factual sources, and twelve authored stimuli across six science
concepts are prepared outside Git. Revision URLs, CC-BY-SA-4.0 terms, adaptation
notices, excerpt and adapted-document hashes are recorded. Original upstream
HTML hashes are unavailable; retained excerpt hashes are not whole-source hashes.
The six literal and six explanatory queries are intended strata, not confirmed
normal/failure cases. These are **source-grounded authored data**, not natural
user logs or unmodified production documents.

Exact query/name/alias checks found no duplicate of the public product dev set.
However, keyword template structure overlaps dev, broad semantic repair
mechanisms may overlap, exhaustive qrels review is pending, and there are only
six independent concept groups. The material is quarantined as a provisional
pilot. **Template independence and semantic independence are not certified.**
Do not exclude inconvenient queries, inflate to120 samples, relabel this pilot
as a real-world benchmark, or score it and then optimize prompts/thresholds.

## Free commands and isolation

```bash
PYTHONPATH=src python -m searchclinic.research.phase2 prepare \
  --corpus /private/corpus.json --stimuli /private/stimuli.json \
  --label-commitment <sha256-of-separate-label-file> --out /private/new-preparation
```

This command reads no qrels. It freezes a separate public input manifest,
creates identical strict query/observation/tokens/search/grep/similar-token/
document contexts, runs a finite RulesPlus worker in another interpreter,
and prepares the same one-shot request for an LLM without making a call.
No healthy-query list, label, qrels, baseline nDCG or gate feedback crosses the
candidate API. No score or verdict feeds a later query or candidate retry.
Outputs are exclusively created: manifest, candidate seal, requests and status.
Use a new directory for each preparation; do not overwrite earlier candidates.

The worker receives only serialized Context and a minimal environment. Its
audit guard denies the private workspace directories and evaluator import.
This is a **trusted finite-worker process/API boundary**, not a kernel sandbox
for hostile executable plugins. The LLM sees a JSON payload and cannot import
local modules or read private files. A transport does not exist in this turn.

The public input manifest is an independent evaluator-trusted commitment.
The candidate bundle's hash alone is not authenticity proof. Keep the manifest
read-only or in evaluator-controlled storage; a party able to rewrite both
commitments can change inputs. The evaluator checks full documents and contexts,
all arm/query coverage, targets, literal spans, strict fields, source revision,
protocol hash/commit and the separate label-file hash before scoring.

The separate evaluator entry point is:

```bash
PYTHONPATH=src python -m searchclinic.research.phase2.evaluator \
  --bundle /private/both-arms-sealed.json --manifest /private/public-input-manifest.json \
  --labels /evaluator-only/reviewed-labels.json --out /private/new-result.json
```

Actual final scoring currently refuses execution. Only `--synthetic-only`
fixtures with explicit synthetic labels and both offline fixture arms can be
scored for tests. Before a paid pilot, implement the approved model/price/call
manifest and provider adapter, validate token bounds and usage, complete
independent annotation review, and freeze both real candidate arms. No API key
or paid request has been used.

## Evaluation semantics

Each arm gets the unchanged full-set `run_gate` (+0.05 target nDCG, other-query
nDCG/recall/precision losses no more than0.02, mean gate tolerance0.02) and its
own cumulative sandbox. Candidates are already fixed, ordered, maximum3.
Accepted patches enter a ledger; rejected patches are discarded, with all
verdicts and errors preserved only in the evaluator. Literal spans establish
term occurrence, not semantic equivalence. This Phase2 guard deliberately
does not veto all semantic candidates using a morphological similarity cutoff.

Detector settings are the existing uncalibrated rules. Both arms use the same
fixed expected action profile and zero expected-latency weight. Measured
generation cost is recorded separately; model acquisition cost is not silently
treated as zero. The protocol's `actions` weight maps to the legacy utility's
`unnecessary_actions` parameter with the same value0.005.

Common preparation calls, arm generation usage and full gate search/reindex
costs are separate. Slow/unknown-cost abstention is not healthy classification.
Healthy diagnosis attempts, submissions, accepted patches and final regressions
are separate counts. Group bootstrap is descriptive below20 concept groups;
synthetic fixtures or this authored pilot cannot support a superiority or
generalization claim. Final-qrels gate acceptance is offline evaluation, not
evidence of safe label-free adoption in production.

Application documents and npuloop review records are outside Git and not part
of this repository's artifacts. See `PHASE2_MODEL_BUDGET.md` for unapproved
official-price proposals and remaining execution prerequisites.
