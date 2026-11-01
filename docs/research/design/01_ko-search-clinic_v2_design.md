# ko-search-clinic 연구 확장 설계서

작성일: 2026-10-11  
대상 저장소: `sokldjs554/ko-search-clinic`  
기준 커밋: `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`

## 1. 목표

`ko-search-clinic`을 범용 챗봇으로 바꾸지 않는다. 기존의 강점인

`검색 실패 진단 → 타입이 있는 처방 → 전체 평가셋 재실행 → 회귀 시 기각 → 증거 원장`

흐름을 유지하면서, 다음 연구 질문을 검증하는 시스템으로 확장한다.

> 한국어 검색/RAG 시스템은 검색 실패를 스스로 감지하고, 정상 질의 회귀와 실행 비용을 고려해 필요한 복구 행동만 선택할 수 있는가?

연구 가제:

- 한국어: **회귀·비용 제약하에서 한국어 검색 실패를 선택적으로 복구하는 LLM Agent**
- 영어: **Selective Retrieval Repair for Korean Search under Regression and Cost Constraints**

## 2. 현재 상태

현재 평가셋은 건강 질의 20개와 실패 질의 16개로 구성되며, 실패 질의에는 다섯 계열이 라벨링되어 있다.

1. `spelling_variant`
2. `cross_script`
3. `synonym_gap`
4. `compound_locked`
5. `garbage_split`

현재 진료 루프는 최대 3회의 처방 제출과 게이트 피드백 재시도를 지원한다. 다만 보관된 Claude 결과에서는 16개 실패 질의가 첫 제출에 모두 통과해, 실제 `기각 → 피드백 해석 → 재처방` 능력은 충분히 측정되지 않았다.

현재 프로젝트가 이미 가진 강점:

- 진단·처방·검증·롤백의 명시적 상태 흐름
- 규칙, 확장 규칙, 벡터, LLM 의사를 동일 평가셋에서 비교
- 실패 질의 개선과 건강 질의 회귀를 동시에 측정
- 과잉 동의어를 자동 기각하는 회귀 게이트
- 결과·원장·문서 간 일치 검증
- 오프라인 재현 경로와 실제 LLM 경로의 구분
- 부정적 결과와 측정 결함을 문서에 보존

현재 연구 주장에 남은 핵심 공백:

- 어떤 질의에 복구가 필요한지 자동으로 판단하는 실패 탐지기가 없다.
- 모든 실패 사례가 미리 선정되어 있어 실제 선택적 개입 성능을 재기 어렵다.
- 첫 제출이 모두 통과해 재시도 정책의 효과가 관측되지 않았다.
- 직접 설계한 36개 질의 밖에서의 일반화 증거가 부족하다.
- 정확도와 회귀는 측정하지만 토큰·호출·지연을 포함한 정책 효용 비교가 없다.
- 의미적으로 부적절하지만 우연히 검색 지표를 높이는 패치를 막는 근거 계약이 약하다.

## 3. 검토한 접근

### 접근 A — 일반 RAG 챗봇으로 확장

문서 업로드, 채팅 UI, 출처 표시를 추가하는 방식이다.

- 장점: 빠르게 시연 가능
- 단점: 기존 차별점이 사라지고 흔한 포트폴리오로 보인다.
- 판단: **채택하지 않는다.**

### 접근 B — 기존 게이트 위에 선택적 복구 연구 계층 추가

기존 검색 엔진과 패치 게이트는 유지하고, 그 앞에 `실패 탐지기`와 `행동 정책`을 추가한다.

- 장점: 현재 검증 자산을 재사용한다.
- 장점: 실패 탐지와 복구 선택의 효과를 분리해 평가할 수 있다.
- 장점: 대학원 연구 주제로 설명하기 쉽다.
- 단점: held-out split과 비용 계측을 새로 설계해야 한다.
- 판단: **권장안이며 본 설계가 채택한다.**

### 접근 C — 데이터셋과 시스템을 전면 재작성

새 외부 코퍼스, 새 검색 스택, 새 Agent 프레임워크를 한 번에 만든다.

- 장점: 확장성이 크다.
- 단점: 기존 결과와 비교가 어려워지고 범위가 과도하다.
- 판단: 외부 일반화 실험 단계에서 필요한 부분만 점진적으로 도입한다.

## 4. 제안 아키텍처

```text
Query + Retrieval Trace
          │
          ▼
Observation Adapter
- top-k score / margin
- result count
- lexical coverage
- BM25↔dense agreement
- evidence conflict
- answer grounding signal
          │
          ▼
Failure Detector
- rules baseline
- small calibrated model
- optional LLM judge
          │
          ▼
Selective Repair Policy
- no_op
- typed_patch
- rewrite_query
- switch_or_fuse_retriever
- rerank
- abstain
          │
          ▼
Existing Executor / Regression Gate
          │
     accepted / rejected
          │
          ▼
Artifact Ledger
- quality delta
- healthy regression
- action count
- latency / tokens / cost
- evidence ids
```

### 4.1 Observation Adapter

기존 검색 실행에서 연구에 필요한 특징만 추출한다. 원시 검색 구현을 연구 모듈이 직접 알지 않도록 `RetrievalObservation`이라는 고정 스키마로 변환한다.

필수 필드:

- `query_id`, `query`, `split`, `family`
- `result_count`
- `top1_score`, `top2_score`, `score_margin`
- `lexical_coverage`
- `retriever_agreement`
- `evidence_conflict`
- `grounding_score`
- `baseline_ndcg`, `baseline_recall`
- `latency_ms`

값을 측정하지 못하면 임의의 기본값을 넣지 않고 `None`으로 남긴다.

### 4.2 Failure Detector

세 단계로 비교한다.

1. **Rule detector**: 결과 0건, 낮은 lexical coverage, 낮은 score margin 등 명시적 규칙
2. **Calibrated lightweight detector**: logistic regression 또는 동등한 작은 분류기
3. **Optional LLM judge**: 근거와 검색 결과를 구조화된 스키마로 판정

출력:

- `failure_probability`
- `predicted_failure`
- `failure_reason_codes`
- `calibration_version`

LLM 판정만으로 패치를 자동 채택하지 않는다.

### 4.3 Selective Repair Policy

정확도 최대화만이 아니라 다음 효용을 사용한다.

```text
utility = quality_gain
          - λ_regression × healthy_regression
          - λ_call × model_calls
          - λ_token × total_tokens
          - λ_latency × latency_ms
          - λ_action × unnecessary_actions
```

`λ`는 dev split에서만 고정하고 test를 본 뒤 변경하지 않는다.

정책은 최소한 다음 행동을 지원한다.

- `no_op`: 현재 결과를 유지
- `typed_patch`: 기존 사용자사전·동의어·복합어 처방
- `rewrite_query`: 검색용 질의를 재작성
- `switch_or_fuse_retriever`: BM25/dense/hybrid 선택
- `rerank`: 상위 후보 재정렬
- `abstain`: 충분한 근거가 없을 때 보류

첫 구현에서는 규칙 기반 정책을 기준선으로 삼는다. LLM 정책은 동일 행동 공간에서 비교한다.

### 4.4 Existing Gate Adapter

현재 `ClinicExecutor`와 게이트를 바꾸지 않고 어댑터로 호출한다.

보장해야 할 계약:

- 건강 질의 전체 재평가
- 기존 허용치 유지
- 기각 피드백을 다음 정책 단계에 전달
- 최대 제출 횟수와 행동 예산 초과 시 fail-closed
- 채택된 패치와 근거 ID 저장

### 4.5 Artifact Ledger

모든 연구 결과의 단일 출처는 JSON/JSONL로 둔다. Markdown 표를 손으로 관리하지 않는다.

권장 경로:

```text
artifacts/research/
├── protocol.json
├── splits/
├── observations/
├── runs/
├── summaries/
└── costs/
```

각 run은 다음을 포함한다.

- git SHA
- Python·Kiwi·모델 버전
- seed
- 데이터 split hash
- detector/policy 설정
- 질의별 전후 지표
- 건강 질의 회귀
- action trace
- 토큰·호출·지연·비용
- 실패·예외

## 5. 평가 설계

### 5.1 데이터 계층

- `controlled-v1`: 기존 20 healthy + 16 failing
- `heldout-expression`: 같은 개념이지만 개발 중 보지 않은 표현
- `heldout-failure`: 개발 중 보지 않은 실패 원인
- `cross-domain`: 공개 데이터 또는 명시적 합성 외부 도메인

동일 문서, 질의 템플릿, 동의어 군이 split을 넘지 않도록 누수 검사를 둔다.

### 5.2 기준선

최소 비교군:

1. no repair
2. current scripted
3. rules+
4. current vector+
5. always rewrite
6. always typed patch
7. current Claude one-shot doctor
8. selective rule policy
9. selective LLM policy
10. oracle upper bound — 결과 해석에서 별도 표시

### 5.3 지표

실패 탐지:

- AUROC, AUPRC
- Precision, Recall, F1
- Brier score, ECE
- 건강 질의 false-positive rate

복구:

- nDCG@10, Recall@k, Precision@5
- failure recovery rate
- healthy regression count/rate
- first-pass acceptance
- rejection 후 recovery rate
- 평균 제출 횟수

비용:

- search/model call count
- input/output tokens
- wall-clock latency
- 유료 API 비용
- quality-cost frontier

답변 단계는 검색 단계가 안정된 뒤 소규모 고정 평가로 추가한다.

- citation correctness
- groundedness
- unsupported claim rate
- abstention accuracy

## 6. 실제 재시도 능력 평가

현재 첫 제출 16/16 통과 결과와 별도로 blind-repair protocol을 만든다.

- Agent에게 qrels와 건강 질의 전체를 노출하지 않는다.
- 첫 단계에는 표적 질의의 제한된 관측만 준다.
- 게이트 기각 뒤에는 회귀가 난 질의와 지표 변화만 반환한다.
- 최대 3회 제출한다.
- 매 회차의 진단, 행동, 피드백, 수정 내용을 저장한다.

인위적으로 틀리게 만드는 프롬프트는 사용하지 않는다. 부분 관측 아래에서 합리적인 첫 처방이 회귀를 일으킬 수 있는 사례를 별도 구성한다.

## 7. 의미 타당성 Gate

검색 지표를 우연히 높이는 잘못된 동의어가 자동 채택되지 않도록 한다.

자동 채택에는 다음 중 하나 이상이 필요하다.

- 공개 사전/원문 근거 ID
- 질의 또는 문서 안의 evidence span
- 독립된 두 신호의 합의
- 구조화 LLM 판정 + 실제 원문 grounding

근거가 없으면 `review_required` 또는 `abstain`으로 끝낸다.

Negative controls:

- 임베딩 유사도만 높은 무관어
- 짧고 다의적인 토큰
- 과도하게 넓은 동의어 군
- 교차 언어 표기지만 다른 개념
- 표적 지표만 우연히 높이는 패치

## 8. 코드 경계

권장 신규 패키지:

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

기존 `doctor`, `patch`, `evaluation`, `rag` 코어는 가능한 한 변경하지 않는다. 새로운 연구 계층이 어댑터로 호출한다.

권장 명령:

```text
clinic research audit
clinic research prepare
clinic research baseline
clinic research run
clinic research report
```

기존 명령과 출력 계약은 유지한다.

## 9. 테스트 전략

필수 테스트:

- split 간 문서·질의·템플릿·동의어 군 누수 차단
- test split으로 threshold/λ를 선택할 수 없음
- 결측 observation을 0으로 위조하지 않음
- 건강 질의에서 `no_op` 선택
- 실패 확률은 높지만 근거가 없으면 `abstain`
- 행동 예산 초과 시 fail-closed
- 의미 근거 없는 패치 자동 채택 차단
- 기각 피드백 후 수정 행동 선택
- 비용·토큰·지연 집계
- 동일 seed deterministic replay
- artifact와 생성 보고서 숫자 일치
- 기존 v1 전체 회귀 없음

기본 CI는 API 키 없이 실행한다. 실제 LLM 실험은 수동 workflow로 분리하고 실행되지 않은 결과를 성공으로 기록하지 않는다.

## 10. 단계별 구현

### Phase 0 — 감사와 프로토콜

- 현재 수치·분모·원장·문서 일치 감사
- 연구 질문, 가설, 성공 기준 사전 고정
- data card와 split contract 작성

### Phase 1 — 선택적 복구의 최소 연구 단위

- observation schema
- rule detector
- cost-aware rule policy
- existing gate adapter
- artifact ledger
- 오프라인 기준선 평가

### Phase 2 — held-out와 실제 재시도

- held-out expression/failure split
- blind repair protocol
- semantic validity gate
- calibration 평가

### Phase 3 — LLM 비교와 답변 전파

- LLM detector/policy
- small answer-grounding evaluation
- quality-cost frontier
- 외부 또는 cross-domain 평가

UI는 Phase 3 이후에 연구 결과를 보여주는 workbench로만 추가한다. 채팅 UI를 핵심 화면으로 만들지 않는다.

## 11. 완료 기준

다음 조건을 모두 만족해야 연구 확장 완료로 본다.

- 기존 테스트 전체 통과
- 신규 연구 테스트 전체 통과
- train/dev/test 누수 검사 통과
- 오프라인 기준선 실제 실행
- 질의별 artifact 생성
- 문서 수치가 artifact에서 자동 생성
- 건강 질의 회귀와 불필요 행동률 보고
- 비용·지연·토큰 보고
- 최소 한 개의 실제 `기각 → 재처방` 사례 관측 또는 관측 실패를 정직하게 기록
- held-out 결과와 신뢰구간 보고
- 부정적 결과와 미해결 한계 기록
- 비밀키·개인정보 미포함 확인

## 12. 대학원 지원에서의 표현

사용 가능한 표현:

> 한국어 검색 실패를 진단하고 수정안을 전체 평가셋에 재적용해 정상 질의 회귀가 발생하면 자동 기각하는 시스템을 구축했으며, 이를 실패 감지와 비용 인지형 선택적 복구 정책 연구로 확장하고 있다.

검증 전 사용하면 안 되는 표현:

- 외부 데이터에서도 일반화가 입증됐다.
- 선택적 Agent가 모든 기준선보다 우수하다.
- LLM이 스스로 안정적으로 재처방한다.
- 실제 서비스 로그에서 효과가 검증됐다.
- 한국어 RAG 신뢰성 문제를 해결했다.
