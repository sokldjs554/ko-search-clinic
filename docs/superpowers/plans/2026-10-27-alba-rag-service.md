# Alba RAG implementation plan

**Goal:** 검색 실패 진단 → 검색 문서 인용 → 구조화 수정 후보 → 기존 회귀 게이트 → 근거를 확인하는 데모와 지원 문서.
**Base:** 80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1
**Branch:** feat/alba-rag-service-20261027
**Scope:** approved 2026-10-26, resumed 2026-10-27. See spec.

## Tasks
1. Recover state / baseline tests. Record unavailable original implementation. [recovery done]
2. `rag/explanation.py`, `tests/test_explanation.py`: strict output, exact source citation, abstention, structured candidate conversion; tests before implementation.
3. `rag/openai_provider.py`, provider tests: bounded Responses request, no retry, cost reservation, secret-safe errors, usage. Freeze evaluation before actual calls.
4. `api/explanation_api.py`, REST integration, web assets: retrieval → generation → validation → gate; default disabled paid provider, replay/live modes, input bounds, cancellation and mobile states.
5. `scripts/evaluate_alba.py`, fixed cases + Actions: actual API report ≤24 calls / $0.30, raw failures preserved, no automatic reruns. Capture hashes and environment.
6. Browser desktop/mobile + full regression suite. Final fresh reviewer for this branch; address findings.
7. README and job matrix; Alba cover letter and portfolio based only on verified evidence. PDF render check and durable delivery.

## Verification / review focus
Citation text must exist in supplied docs; abstention cannot contain executable candidate; candidate target must match query; invalid schema/incomplete API cannot apply patches; gate rejections remain rejected; qrels excluded; budget consumed on uncertain transport failure; keys never in reports; replay must not impersonate generation; UI renders model text as text, not HTML.

## Rulings
- R1: Prior uncommitted changes unrecoverable. Rebuild from approved scope instead of claiming old tests passed.
- R2: Dedicated clean clone is already isolated; create feature branch here, no extra worktree needed.
- R3: Existing secret reuse and API budget were explicitly approved; no repeated credential permission request.

## Ledger
No live API calls made at plan creation. No application claims finalized before results.
- R4: Kiwi default cong mis-segmented '포도'; 0.21.0 produced additional corpus regressions. Pin Kiwi 0.24.1/model 0.24.0 and explicitly select cong-global. Analyzer/corpus/real-gate tests: 28 passed, 1 deselected. Full regression remains required.
- R5: Remove a test that equated README's historical test count with the current collection count. Optional dependencies and --ignore make this equality invalid. Record actual commands, environments and counts in dated verification results; retain behavioral corpus tests.

- R6: Shell git push has no credentials. Publish through the connected GitHub Git Data API; no new tokens requested or secret extraction.
- Review: fresh reviewer found stale input/apply state, evaluator misclassification of invalid patches, and p95 floor bias. Inputs now invalidate the current report/citations and are locked during generation; duplicate patches fail validation; unknown-query and malformed-candidate failures are distinct; p95 uses nearest rank. Follow-up tests added.
