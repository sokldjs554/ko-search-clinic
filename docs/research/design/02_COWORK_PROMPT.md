# Cowork에 보낼 요청문

아래 내용을 그대로 전달하면 됩니다.

---

GitHub 저장소 `sokldjs554/ko-search-clinic`을 확인하고, 기존 프로젝트를 범용 챗봇으로 바꾸지 않은 채 **선택적 검색 실패 복구 연구 시스템**으로 확장해 주세요.

기준 브랜치/커밋:

- 저장소: `sokldjs554/ko-search-clinic`
- 기준: `main`의 `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`
- 작업 브랜치: `feat/selective-retrieval-repair-v2`

먼저 첨부한 `01_ko-search-clinic_v2_design.md`를 읽고, 그 설계를 구현 계획의 기준으로 사용하세요.

## 절대 바꾸면 안 되는 방향

이 프로젝트를 다음과 같이 만들지 마세요.

- 문서 업로드형 RAG 챗봇
- 채팅 UI 중심 데모
- LangChain/LangGraph를 붙인 것만으로 Agent라고 주장하는 프로젝트
- 기존 16/16 결과를 외부 일반화 결과처럼 포장하는 프로젝트
- 실행하지 않은 실험 수치를 README에 먼저 적는 프로젝트

현재 핵심인

`검색 실패 진단 → 타입이 있는 처방 → 전체 평가셋 재실행 → 회귀 시 기각 → 증거 원장`

흐름을 보존해야 합니다.

## 이번 작업의 연구 질문

> 한국어 검색 시스템이 검색 실패를 스스로 감지하고, 정상 질의 회귀와 실행 비용을 고려해 필요한 복구 행동만 선택할 수 있는가?

## 작업 순서

### 1. 현재 상태 감사

아래를 실제 코드·데이터·테스트·문서로 대조하세요.

- 건강 질의 20개, 실패 질의 16개, 총 36개가 맞는지
- 실패 계열 5개와 expected patch kind가 일치하는지
- README의 16/16, nDCG 0.980, 건강 질의 회귀 0건이 현재 artifact와 일치하는지
- Claude 실행의 모델 ID·프롬프트 버전·원장 provenance
- `MAX_SUBMITS=3` 재시도 경로가 실제로 어떤 테스트로 고정돼 있는지
- RAG retrieval 결과, 벡터 캐시 coverage, 청킹 결과의 최신 값
- Elasticsearch 설정 렌더링과 실제 Elasticsearch 실행 증거의 구분
- CI가 실제로 실행하는 검사와 문서 대조만 하는 검사의 구분

결과를 `docs/research/CURRENT_STATE_AUDIT.md`에 작성하세요. 재실행하지 못한 것은 `미확인`으로 적으세요.

### 2. 프로토콜 사전 고정

최종 test 결과를 보기 전에 다음을 작성하고 먼저 커밋하세요.

- `docs/research/PROTOCOL.md`
- `docs/research/DATA_CARD.md`

프로토콜에는 연구 질문, 가설, split, 기준선, 성공/기각 기준, 통계 방법, 비용 측정, 중단 조건을 포함하세요. test 결과를 본 뒤 기준을 바꾸지 마세요.

### 3. 연구 계층 추가

기존 코어를 가능한 한 건드리지 말고 아래 패키지를 추가하세요.

```text
src/searchclinic/research/
├── __init__.py
├── models.py
├── observations.py
├── detector.py
├── calibration.py
├── actions.py
├── policy.py
├── gate_adapter.py
├── metrics.py
├── splits.py
├── costs.py
├── artifacts.py
├── runner.py
└── cli.py
```

필수 흐름:

```text
retrieval trace
→ normalized observation
→ failure detector
→ selective repair policy
→ existing ClinicExecutor/regression gate
→ artifact ledger
```

### 4. 최소 행동 공간

- `no_op`
- `typed_patch`
- `rewrite_query`
- `switch_or_fuse_retriever`
- `rerank`
- `abstain`

처음에는 규칙 기반 detector와 policy를 구현하세요. 그 다음 동일 행동 공간에서 LLM detector/policy를 선택 실험으로 추가하세요.

### 5. 필수 평가

실패 탐지:

- AUROC, AUPRC, Precision, Recall, F1
- Brier score, ECE
- 건강 질의 false-positive rate

복구:

- nDCG@10, Recall@k, Precision@5
- failure recovery rate
- healthy regression rate
- first-pass acceptance
- rejection 후 recovery rate
- 평균 제출 횟수

비용:

- 검색 호출 수
- 모델 호출 수
- input/output tokens
- latency
- 실제 API 비용

`always repair`와 `selective repair`를 반드시 비교하세요.

### 6. 실제 재처방 평가

현재 보관 결과는 첫 제출 16/16 통과이므로 실제 자가 수정 능력이 측정되지 않았습니다.

별도의 blind repair 평가를 구현하세요.

- qrels와 건강 질의 전체를 Agent에게 노출하지 않음
- 첫 처방이 기각되면 회귀 질의와 지표 변화만 반환
- 최대 3회 제출
- 회차별 진단·행동·피드백·수정 기록
- 인위적으로 틀리게 만드는 프롬프트 금지

### 7. 의미 타당성 Gate

지표를 우연히 높이는 잘못된 동의어를 자동 채택하지 마세요. 자동 채택에는 사전/원문 근거 ID 또는 evidence span이 필요합니다. 근거가 없으면 `review_required`나 `abstain`으로 끝내세요.

### 8. TDD와 검증

프로덕션 코드를 쓰기 전에 실패 테스트를 먼저 작성하고 실제로 실패하는 것을 확인하세요.

필수 테스트:

- split 누수 차단
- test로 threshold를 튜닝할 수 없음
- 결측 관측값을 0으로 처리하지 않음
- 건강 질의에서 no-op
- 근거 없는 고위험 사례에서 abstain
- 행동 예산 초과 시 fail-closed
- 의미 근거 없는 패치 자동 채택 차단
- 기각 후 수정 행동
- 비용 집계
- deterministic replay
- artifact와 보고서 숫자 일치
- 기존 v1 테스트 회귀 없음

기본 CI는 API 키 없이 통과해야 합니다. 실제 LLM 실험은 별도 수동 workflow로 두세요.

## 문서와 결과 관리

결과의 단일 출처는 `artifacts/research/**/*.json` 또는 `.jsonl`로 두고 Markdown 숫자를 손으로 적지 마세요.

완료 문서:

- `docs/research/CURRENT_STATE_AUDIT.md`
- `docs/research/PROTOCOL.md`
- `docs/research/DATA_CARD.md`
- `docs/research/BASELINES.md`
- `docs/research/RESULTS.md`
- `docs/research/FAILURE_ANALYSIS.md`
- `docs/research/LIMITATIONS.md`
- `docs/research/REPRODUCIBILITY.md`
- `docs/research/PAPER_OUTLINE.md`

README는 실제 결과가 생성된 뒤에만 수정하세요.

## 완료 보고 형식

완료됐다고 말하기 전에 다음을 모두 실제 출력으로 확인하세요.

1. 기존 전체 테스트 통과
2. 신규 전체 테스트 통과
3. split 누수 검사 통과
4. 오프라인 기준선 실행
5. 질의별 artifact 생성
6. 건강 질의 회귀 결과 확인
7. 비용·지연·토큰 집계 확인
8. 부정적 결과와 한계 기록
9. 새 환경 재현 명령 실행
10. 비밀키·개인정보 없음

마지막 보고에는 다음을 포함하세요.

- 구현한 내용
- 실행한 명령
- 실제 검증 수치
- 기각된 가설
- 남은 한계
- 변경 파일
- 커밋 SHA
- 지원서에 사용할 수 있는 주장과 아직 사용하면 안 되는 주장

중간에 기능을 무작정 늘리지 말고, **실패 감지와 선택적 복구 정책이 회귀와 비용을 줄이는지 검증하는 것**에만 집중하세요.

---
