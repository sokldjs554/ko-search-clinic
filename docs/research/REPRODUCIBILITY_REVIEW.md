# a0fc8c7 재현성 점검과 사후 정책 변경 판단

보존 기준: `a0fc8c7abe8a04d932de382e28e5ccd93b3cdc1f`.
기존 `phase01-v1` 프로토콜, 원본 run·report·threshold와 main/v1은 수정하지 않는다.
이 점검은 Phase 2 기능 추가가 아니다.

## 변경 전 판단 근거

runner.propose_candidates는 진단과 후보 생성에 이미 소요한 perf_counter 지연을
각 Candidate.cost에 넣는다. select_action은 이 cost의 latency를 utility에서
빼고 양수가 아니면 abstain한다. 모든 후보에 동일한 sunk diagnostic cost를
다시 붙이는 것이며, 앞으로 gate/patch에 드는 시간을 예측한 값은 아니다.

v1 프로토콜은 실측 진단 지연 사용을 명시했다. 따라서 구현은 그 지시를
따르지만, 별도의 deadline 또는 남은 시간 예산을 검사하는 정책은 아니다.
같은 관측·후보 내용·설정에서 환경 부하와 cold/warm cache만 바뀌어도 선택이
달라진다. 지연을 replay 비교에서 빼는 기존 계약과 충돌한다.

변경 전에 실제 함수로 확인한 통제 실험: failure score=0.95,
min_gain=0.05, action penalty=0.005, latency weight=0.00001이다.
`후라이팬`의 동일한 실제 RulesPlus 후보에서 측정 비용만 바꾸면 4249ms에는
typed_patch, 4250ms에는 nonpositive_utility에 의한 abstain이 된다.
이는 정책 경계 probe 입력이며 실서비스 지연 성능이나 속도 측정값이 아니다.
두 경우 모두 predicted_failure=true이다. 보류를 정상 판정으로 바꾸지 않는다.

## 최소 변경안 — phase01-v2

1. 기존 Candidate.cost와 select_action 기본 경로는 measured-v1로 유지한다.
2. Candidate에 별도의 expected_cost를 추가한다. 새 정책만 실행 전 고정된
   expected_cost를 utility에 사용한다. 이미 측정한 비용은 원장과 실제 비용
   집계에 남기며 미래 비용으로 사용하지 않는다.
3. 아직 검증된 미래 latency 모델이 없다. phase01-v2에서는 expected latency를
   null로 남기고 latency weight를 0으로 지정해 그 미측정 항을 효용에서 제외한다.
   실측 latency를 0으로 바꾸거나, 임의 시간을 성능 측정치로 제시하지 않는다.
   외부 호출/토큰/action 페널티와 제출 예산은 그대로 유지한다.
4. 미래 비용의 필수 호출/토큰/금액이 미확인이면 abstain한다. latency weight가
   양수인데 expected latency가 미확인이어도 abstain한다.
5. detector와 threshold, seed, evalset, 후보 생성 규칙, gate는 변경하지 않는다.

새 프로토콜은 `artifacts/research/versions/phase01-v2/protocol.json`에 별도
고정하고 SHA256으로 검증한다. 기존 v1은 기존 사전 커밋 검증을 그대로 유지한다.
기존 결과를 본 뒤 제안한 사후 변경이며 성능 개선의 사전 검증으로 주장하지 않는다.
새 실행 root와 별도 결과에서만 평가한다. 기존 run과 새로운 source hash를
같은 비교군으로 섞지 않는다.

## 실행·테스트 계획

- v1 지연 경계와 실패/보류 구분을 재현 테스트로 고정한다.
- v2에서 측정 지연만 변해도 동일 예상 비용 아래 선택이 유지되는지 검사한다.
- 예상 비용이 높거나 미확인일 때 abstain하며 failure=true 유지 여부를 검사한다.
- 실제 runner 후보의 expected/measured 분리와 원장 기록을 확인한다.
- 기존 명령의 기본 v1 경로를 유지하고 v2는 명시적인 버전 옵션으로 실행한다.
- 새 프로토콜을 커밋한 뒤 별도 오프라인 run, 기존·신규 전체 테스트를 실행한다.
- PR CI의 head, 실제 checkout, 연구 source hash와 skip을 각각 기록한다.

## 결과 표현 계약

아답터는 RulesPlus의 순차 후보 재시도다. LLM이 피드백을 이해한 자가 수정
실험이 아니다. 건강 개입은 진단 시도를 포함하며 제출·채택과 별도 분모다.
검색 호출 감소는 LLM 토큰/API 비용 절감의 증거가 아니다. 단일 wall-clock은
속도 우위의 근거가 아니다. 모든 현재 결과는 공개 controlled-v1/dev이며,
향후 held-out 결과와 분리한다.
