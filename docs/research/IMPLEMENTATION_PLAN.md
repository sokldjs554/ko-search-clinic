# Selective Retrieval Repair Phase 0–1 Implementation Plan

> **For agentic workers:** Implement inline with superpowers:executing-plans;
> follow test-driven-development and verification-before-completion.

**Goal:** 기존 처방·게이트를 유지하는 오프라인 선택적 복구 연구 단위.
**Architecture:** 관측과 evaluator label 분리; rules+ 후보와 기존 run_gate 재사용;
> immutable JSON과 자동 생성 보고서로 판정·비용 기록.
**Tech Stack:** Python, Pydantic, Kiwi, pytest, 표준 라이브러리.
**Spec:** `docs/research/design/01_ko-search-clinic_v2_design.md`와 `PROTOCOL.md`.

## Global Constraints

- branch `feat/selective-retrieval-repair-v2`, v1 데이터·결과·명령 보존.
- Phase 0–1만 실행, API 키 없이 동작, test 결과 전 protocol 커밋.
- MAX_SUBMITS=3, min_gain=0.05, epsilon=0.02; missing=null.
- README는 실험 이후; 새 임의 수치·LLM·held-out 결과 금지.

## Review Focus

- labels가 정책으로 새면 안 된다: policy_view의 필드 제거와 label mutation 테스트.
- missing/nonfinite 비용과 근거는 fail-closed: 범위·NaN·span 검사 테스트.
- 마지막 채택이 이전 정상 질의를 망가뜨리면 안 된다: 최종 전체 회귀 검사.
- audit/report도 과거 run을 덮어쓰면 안 된다: 동일 경로 재기록 오류 테스트.
- 타이/단일 클래스 탐지 지표를 정확하게 처리: 수기 계산 사례 테스트.

### Task 1: 감사와 사전 고정

- [ ] v1 전체 테스트/기준선/네 규칙 엔진/RAG/cache/청킹 실측, CI provenance 조회.
- [ ] 감사와 data card/protocol/protocol.json/입력 문서를 별도 커밋.
- [ ] 버전 변화 및 README 테스트 분모 오류는 결과를 덮어쓰지 않고 기록.

### Task 2: 관측·split·탐지·정책 계약

Files: `research/models.py`, `splits.py`, `observations.py`, `detector.py`,
`calibration.py`, `actions.py`, `policy.py`, `costs.py`; tests `test_research_contracts.py`.
Interfaces: `observe(engine, query, query_id, split) -> RetrievalObservation`,
`RuleDetector.detect(observation) -> Detection`, `select_action(...) -> Decision`,
`validate_splits(rows, evalset, docs)`, `freeze_config(rows, config)`.

- [ ] 실패 테스트: null 보존, label 미노출, split 각 누수, test 튜닝 차단,
  healthy no_op, 근거 부재 abstain, utility 비용/예산 차단, 비용 null 합산.
- [ ] 실행해서 누락된 기능 때문에 실패 확인 후 최소 구현.
- [ ] 해당 테스트를 실행하고 통과 확인.

### Task 3: 후보·게이트·연구 실행

Files: `research/gate_adapter.py`, `runner.py`, `metrics.py`;
tests `test_research_execution.py`.
Interfaces: `GateAdapter.submit(candidate)`, `run_experiment(policy, manifest, protocol)`;
run output는 JSON 직렬화 가능한 dict, accepted/rejected/reasons/evidence/cost trace 포함.

- [ ] 실패 테스트: 전체 evalset 필수, 원문 span 검증, target 불일치,
  과잉 동의어 기각/좁힌 처방 채택, 실제 예산/검색/재색인 계측,
  AUROC 동률/AP/Brier/ECE, deterministic 판정 replay.
- [ ] 실패 확인 후 rules+ 어댑터와 run_gate 호출 계층 구현.
- [ ] 전체 질의 비교군을 새 엔진에서 실행하고 최종 회귀 검사.

### Task 4: artifact·CLI·CI·재현

Files: `research/artifacts.py`, `cli.py`, 기존 `src/searchclinic/cli.py`에 subcommand만;
CI 추가, docs/research reports; tests `test_research_artifacts.py`.
Interfaces: `write_artifact(path, payload)`, `render_report(runs)`, `clinic research ...`.

- [ ] 실패 테스트: artifact immutability, 보고서 숫자 일치, hash mismatch 차단,
  기존 CLI 보존과 연구 prepare/run/report 실제 실행.
- [ ] 실패 확인 후 구현; 기존 CI 명령 유지하고 연구 실행 추가.
- [ ] 오프라인 baseline/run/report, v1+신규 전체 pytest, baseline 실행.
- [ ] 실행 결과 후 README 테스트 수 계약의 알려진 오류를 수정.
- [ ] 새 venv에 설치/재현 실행, secret/v1 hash/diff 검토, 커밋.
