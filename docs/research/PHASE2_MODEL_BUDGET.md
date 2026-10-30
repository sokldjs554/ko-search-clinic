# Phase 2 model / budget check — not approved, no paid calls

Checked official pages on 2026-10-12. These are published model IDs/prices;
this workspace has no configured provider credential, and account-level access,
rate limits, model response or provider billing have not been tested.

Sources: [OpenAI model/snapshot and pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[Claude current IDs](https://platform.claude.com/docs/en/models/overview),
[Claude standard API prices](https://platform.claude.com/docs/en/about-claude/pricing).
Use standard synchronous, uncached text requests with no server-side tools,
batch discount, fast mode or regional premium. All amounts below are **computed
maximum token charges**, not observed bills. Taxes/currency conversion excluded.

| Model ID | Input/output USD per million tokens | 6000 input + 1500 output maximum/call | Pilot ceiling 14 calls | Old proposal 132 calls |
|---|---:|---:|---:|---:|
| `gpt-4.1-mini-2025-04-14` | 0.40 / 1.60 | 0.0048 | 0.0672 | 0.6336 |
| `claude-haiku-5-5` (prompt ≤100k) | 0.10 / 0.50 | 0.00135 | 0.01890 | 0.17820 |
| `claude-sonnet-5-5` | 2 / 10 | 0.027 | 0.378 | 3.564 |
| `claude-haiku-4-5-20251001` | 1 / 5 | 0.0135 | 0.1890 | 1.7820 |

Formula: `(6000 × input_rate + 1500 × output_rate) / 1,000,000`.
[Haiku4.5 legacy page](https://platform.claude.com/docs/en/models/haiku-4-5/overview)
confirms its dated ID and active legacy status on the check date. Its retirement
commitment is only "not sooner than October15,2026", so recheck before selection.
There is no automatic model substitution.

The small, **provisional** corpus has twelve authored stimuli and six concept
groups. A potential paid pilot would use at most two separate dev sanity calls
and twelve test calls, one ordered list/query and zero automatic retries. Actual
test calls depend on the frozen detector; this is not a prediction of successful
repairs. Dev sanity data must be new fixtures and never final test labels.
The former 132-call/USD5 proposal remains unapproved and unchanged in the older plan.

Recommended first reproducible comparator if/when ready: the named GPT-4.1 mini
snapshot, maximum14 calls, **USD1.00 proposed hard cap**, with price/model/call
manifest frozen after approval. This is a proposal, not authorization. Claude
is a valid alternative; a second LLM arm requires a new same-condition protocol
and separately approved combined budget. The lower listed price does not imply
better quality. Account availability and current price must be checked again
at execution time without silently changing the model.

Free code prepares the same label-free request payload and an offline cost
reservation guard. It does **not** connect keys or contain a live provider
transport. The final evaluator intentionally refuses real paid comparisons
until the approved model/usage/execution manifest is implemented. Missing
usage, overcap input/output, model change, failed transport or unknown price
halt execution; a failed call's full reservation remains held, with no retry.

Do not request execution yet: independent qrels review and template-overlap
resolution are outstanding. No final scores have been read and no paid calls
have been made. All three research-arm results remain pending; synthetic
unit-test gate outcomes are only software verification.
