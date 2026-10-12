# Phase 0–1 사전 고정 연구 프로토콜

버전: `phase01-v1`. 시작 main: `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`.
최상위 설계: [제공 설계](design/01_ko-search-clinic_v2_design.md).
사용자가 허가한 Phase 0–1까지만 실행한다. 이 파일과 protocol.json은 연구
실행 이전 별도 커밋으로 고정한다. 이후 변경은 새 버전으로만 가능하다.

## 질문과 가설

한국어 검색 실패를 관측으로 탐지하고 필요한 처방만 선택하면서 정상 질의
회귀와 실행 비용을 제한할 수 있는가?

H1: selective rule은 always typed patch보다 건강 질의 개입 수와 실제 검색
호출 수를 줄인다. H2: 실패셋 최종 평균 nDCG와 치유 건수는 always typed
patch보다 나빠지지 않으며 건강 질의의 세 지표 회귀는 없다.
H3: 결과 0건 규칙만으로 모든 실패 원인을 탐지할 수 있다.
각 가설은 이 공개 controlled-v1 개발 데이터에 대한 기술적 결과로만 해석한다.
LLM·held-out·일반화·통계적 우위의 주장은 이번 단계의 대상이 아니다.

## 데이터와 누수 경계

기존 코퍼스·qrels·v1 명령·JSON을 수정하지 않는다. 모든 기존 질의는 이미
공개된 `controlled-v1/dev`이다. train/test는 빈 집합이며 held-out-expression,
heldout-failure, cross-domain은 Phase 2–3에서 별도로 수집한다. 빈 test를
성능 평가로 표시하지 않는다. 문서 ID, 정규화 질의, template ID, synonym
group ID가 서로 다른 split에 걸치면 준비 단계에서 실패한다. 동일 연결
성분을 하나의 split에 두며 선언 누락도 오류로 처리한다.

family·qrels·baseline nDCG/recall은 평가와 저장 전용이다. 정책에는 이
필드가 제거된 관측만 전달한다. 개발 fixture의 건강/실패 라벨을 정책
분기로 사용하지 않는다. threshold와 λ 선택은 dev에만 허용하고 train,
test 또는 혼합 입력을 거부한다.

## 고정 detector와 정책

결과 0건: score 0.95, lexical coverage < 0.5: 0.8, 상대 margin < 0.1:
0.6, 그 외 관측 충분: 0.1. score >= 0.5면 predicted failure.
이 score는 규칙 점수이며 보정된 확률이라는 주장을 하지 않는다. 검색
결과 수마저 없으면 판정 보류한다. 결측은 null로 저장한다. 상대 margin은
(top1-top2)/abs(top1), top2가 없거나 top1=0이면 null이다.
lexical coverage는 질의 토큰 중 반환된 문서 토큰에 나타난 고유 토큰 비율이다.

예산은 질의당 최대 3회 제출/3회 repair action이다. no_op와 abstain은 repair
action에 포함하지 않는다. 높은 실패 점수라도 후보의 원문/query span 근거가
없으면 abstain한다. 정상 판정은 no_op이다. 비용 효용이 양수가 아닌 후보는
실행하지 않는다. utility = gain − λ_regression×regression − λ_call×model_calls
− λ_token×tokens − λ_latency×latency_ms − λ_action×unnecessary_actions.
λ는 각각 1, 0.01, 0.000001, 0.00001, 0.005로 사전 지정한다.
선택 시 gain 입력은 rule score×기존 최소 표적 이득이며 qrels를 사용하지 않는다.
후보 비용은 관측된 진단 지연과 후보의 명시적 호출/토큰 요구량이다.
유료 모델을 호출하는 후보는 이번 단계에서 생성하지 않는다.

행동 스키마는 no_op, typed_patch, rewrite_query, switch_or_fuse_retriever,
rerank, abstain을 구분한다. Phase 1 실행기는 기존 typed_patch와 no_op/abstain만
실행한다. 나머지는 unsupported_action으로 보류하며 성공으로 기록하지 않는다.
기각 후 후보가 남으면 피드백을 기록하고 다른 처방을 제출한다. qrels는 후보
생성기에 주지 않는다. 본 단계의 근거 검사는 span 무결성 검사이며 완전한
의미 타당성 검증과 blind repair는 Phase 2로 남긴다.

## 게이트와 중단 기준

기존 run_gate를 어댑터로 호출한다. 최소 표적 nDCG 이득 0.05,
다른 모든 질의 nDCG/recall/precision5 하락 허용 ε=0.02, 전체 평균
하락 허용 ε=0.02를 그대로 유지한다. 건강 질의 전체를 포함한 평가셋이
없으면 어댑터를 생성하지 않는다. 기각·오류·근거 누락·예산 초과에서는
현역 엔진을 승격하지 않는다. target 변경, split hash/프로토콜 불일치,
데이터 누수는 실행 오류다. API 키 없이 오프라인으로 실행한다.

## 비교군과 실행 순서

1. 감사에서 current scripted, rules+, vector, vector+를 기존 루프로 재실행한다.
2. 새 runner에서 no repair, always typed patch, selective rule을 각각 새 엔진으로
   같은 전체 질의 순서(기존 건강 다음 실패)에서 실행한다. 두 repair 정책은
   같은 rules+ 후보 생성·근거 검사·제출 예산을 공유한다.
3. always typed patch는 모든 질의에서 후보 진단을 실행한다. 후보 부재는
   abstain으로 기록한다. selective rule은 건강 판정에서 진단을 생략한다.
4. seed=20261012. 판정 replay는 동일 seed/환경에서 동일해야 한다.
   실제 지연·시각은 deterministic 비교에서 제외하며 조작하지 않는다.

always rewrite, Claude one-shot, selective LLM, oracle upper bound는 미실행으로
구분한다. 관측하지 않은 결과나 유료 API 금액을 만들어 넣지 않는다.

## 지표·성공·기각

탐지 AUROC/AUPRC/Precision/Recall/F1/Brier/ECE(10개 equal-width bin),
건강 FPR을 초기 관측으로 계산한다. AUPRC는 동률 score를 한 threshold로
처리한 average precision이다. 단일 라벨 분포는 정의 불가 지표를 null로 둔다.
복구는 질의별 nDCG@10, recall@10, precision5와 최종 실패 평균, 표적의
게이트 채택에 따른 recovery rate, 건강 회귀 count/rate, first-pass acceptance,
기각 후 recovery, 평균 제출 횟수를 보고한다. precision5는 기존 구현과 같이
반환 결과가 5개 미만이면 실제 반환 개수가 분모다.
불필요 개입은 건강 라벨 질의에 repair 진단 또는 처방을 실행한 경우이며
선택 count와 실제 제출 count를 별도로 기록한다.

H1은 건강 개입 수와 실제 검색 호출 수가 둘 다 감소할 때만 지지한다.
H2는 동일 치유 건수 이상, 평균 nDCG 하락 없음, 세 건강 지표에서 ε 초과
회귀 0건일 때만 지지한다. 하나라도 어긋나면 해당 가설을 기각한다.
H3은 전체 실패를 탐지할 때만 지지한다. 근거 없는 패치 자동 채택은 허용하지 않는다.
성능 수치를 본 뒤 threshold·λ·질의 순서·분모를 바꾸지 않는다.

## 통계와 비용

seed 고정 paired bootstrap(2000회)으로 query nDCG 평균 차이의 기술적 95%
구간을 기록한다. 같은 개념의 질의는 독립 표본이 아니므로 유의성/일반화
판정에 쓰지 않는다. 추후 held-out에서는 연결 성분 단위 bootstrap을 별도
프로토콜로 고정한다. 단일 실행 wall-clock은 속도 우위의 근거로 삼지 않는다.

SearchEngine.search 실제 호출과 sandbox 재색인을 공용 계측기로 센다.
전체 측정 지연과 개별 질의 지연을 perf_counter로 측정한다. 모델 호출은
외부 LLM 호출이며 규칙 함수 호출과 구분한다. 호출 없음이 확인된 오프라인
실행에서만 model_calls/tokens/API 비용을 0으로 기록한다. 알 수 없는 유료
사용량은 null이며 null은 합산 시 0으로 위조하지 않는다.

JSON이 결과 단일 출처다. SHA, 환경 버전, 데이터/split/protocol hash,
설정, 관측, 질의별 전후 지표, 근거, 모든 기각·행동·오류·비용을 저장하고
보고서는 JSON으로부터 생성한다. 기존 v1 파일 hash 보존을 검증한다.
