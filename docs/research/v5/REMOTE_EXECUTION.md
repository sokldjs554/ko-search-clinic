# V5 remote execution and private evidence

Publishing `.github/workflows/v5-judges.yml` performs free preparation only. It
rebuilds the fixed plan with pinned dependencies and verifies SHA-256
`e916e357cd7426a6bb50180559b542b33b28f20dda0189dcfb37ae7ed9d6f99c`.
The preparation and approval steps never receive `OPENAI_API_KEY`. The sole
provider-enabled step is separately gated. Existing model-access preflight is a
GET-only workflow and does not authorize generation.

The approved experiment was `gpt-4.1-mini-2025-04-14`, at most 90 calls and a
maximum configured reservation of USD 0.72. This is a retrospective controlled
development experiment. The dedicated authorization commit `0e7dae7ec66bcac5a93aa9b2961547490f145b9f` was consumed by run41198330827: 90 calls completed. `ops/v5-approved.json` preserves that authorization record; it does not authorize another run. See [actual results](LIVE_EXPERIMENT_20261031.md).

## Recipient setup (local only)

The local key was generated at `work/v5-recipient-private.json` with mode 0600;
only `ops/v5-recipient.json` contains the public key and its SHA-256 fingerprint.
Keep the private key available for recovery. Never add it to Git, Actions secrets,
workflow inputs, logs or public artifacts. Losing it makes the encrypted evidence
unrecoverable. A fresh installation can generate a new recipient before approval:

```sh
umask 077
python scripts/package_v5_evidence.py keygen \
  --private work/v5-recipient-private.json > ops/v5-recipient.json
```

The command refuses an existing private key. Its standard output contains only
public recipient metadata. Commit the public recipient before reviewing the final
code commit; do not rotate it after approving that code.

## Separate paid approval

After explicit user approval of the fixed model, request count, cost ceiling,
plan, and reviewed code, create `ops/v5-approved.json` in a **new dedicated commit**.
Its object has exactly two fields:

- `approved_code_commit`: the full 40-character SHA of the reviewed commit,
  which must be the dedicated approval commit's single parent.
- `transport_approval`: the existing transport approval object with exactly
  `approved: true`, `plan_hash` equal to the fixed hash above,
  `model_id: "gpt-4.1-mini-2025-04-14"`, `max_calls: 90`, and `max_cost_usd: 0.72`.

The only changed path in that commit must be `ops/v5-approved.json`. Its entire
commit message must be:

```text
V5_APPROVED_PLAN=e916e357cd7426a6bb50180559b542b33b28f20dda0189dcfb37ae7ed9d6f99c
```

Push that commit to `feat/research-verification-v5-20261030` only after approval.
The gate checks the actual checked-out head, its parent, changed paths, message,
plan, recipient validity, and `GITHUB_RUN_ATTEMPT == 1`. A read-only Actions API
check also requires this to be the earliest workflow run for the approval commit;
re-pushing the same approval commit cannot automatically execute again. Failures
of that check block generation. Concurrency uses the plan hash and never cancels
a running experiment. Do not use Actions “Re-run jobs”: reruns are blocked.

Any later paid execution requires renewed review of its code and a new explicit approval. Free analysis and documentation changes do not authorize or require another paid run.
Approval files document authorization; they do not authenticate the human who
provided it. Repository write access remains the administrative trust boundary.

## Evidence and retrieval

Preparation, labels, requests, raw responses, outcomes, timing, execution logs and
partial runs stay under the ephemeral runner's `work/remote-evidence/`. Provider
stdout/stderr are redirected there. The workflow encrypts the complete ZIP using
an ephemeral X25519 key, HKDF-SHA256 and AES-256-GCM to the local recipient.
Authenticated associated data binds the plan hash, Actions run ID, recipient
fingerprint and ZIP SHA-256. The private key never reaches Actions.

Only `evidence.enc.json` and an aggregate `receipt.json` are uploaded as
`v5-encrypted-evidence-RUN_ID`, retained for 30 days. The receipt contains hashes,
run ID, byte/file counts and encryption status; it does not contain responses,
labels, per-query results or error text. Encryption runs after ordinary execution
failure or step timeout as well as success. A terminated runner, infrastructure
loss or force-cancelled job cannot guarantee evidence preservation. Never
substitute a plaintext upload if encryption fails.

Download the artifact to a new directory beneath ignored `work/`, verify its
receipt/envelope hash, then decrypt locally with the expected plan and run ID:

```sh
python scripts/package_v5_evidence.py decrypt \
  --envelope work/downloaded-v5/evidence.enc.json \
  --private work/v5-recipient-private.json \
  --plan-hash e916e357cd7426a6bb50180559b542b33b28f20dda0189dcfb37ae7ed9d6f99c \
  --run-id RUN_ID \
  --out work/recovered-v5-RUN_ID
```

Authentication, archive checksum, entry safety, CRC and extraction-size limits are
checked before output creation. Existing output directories, traversal, symlinks,
conflicting ZIP paths and outputs outside ignored `work/` are rejected. Retain the
ciphertext and receipt as the original transfer evidence. Review decrypted
results locally before any later publication decision. A partial run is evidence
of an attempt, not permission to retry it.
