# v5 이전 연구 감사 — 보존 자료와 재사용 경계

작성: 2026-10-30. 기준 main `f3ca14a`. 원격 브랜치 14개의 Git tree/log와 공개 파일을 읽었고, 구현 파일·브랜치·과거 결과는 수정하지 않았다. API 호출·암호화 해제 시도·새 모델 생성은 하지 않았다. 아래 재집계는 저장 JSON을 읽은 오프라인 집계이며 새 검색 실행이나 새로운 독립 성능 결과가 아니다.

## 1. 판정

기존 연구는 버릴 구현이 아니라 **증거 수준과 평가 정책을 분리해 가져올 자산**이다. PR1의 typed action / 관측·정책 경계 / trace, Phase2의 공통 문맥·후보 봉인·비용 예약, v4의 후보별 오류 보존·질의 한정 적용·순위 봉인, RAG24의 원시 출력 재검증은 재사용할 수 있다. 반면 PR1/Phase2의 정답 게이트 점수를 운영 정책의 성능으로 해석하거나 v3/v4의 서로 다른 적용 정책을 같은 실험으로 합치면 안 된다.

가장 큰 불확실성은 v4의 **73 생성 → 63 목록 규약 통과 → 2 적용** 사이의 원인별 손실이다. 실행별 context, 원시 응답, 후보 audit, application_gate, 순위·label 파일이 암호화돼 있으므로 현재 공개 파일만으로 61개 이상이 왜 탈락했는지, 올바른 후보가 있었으나 정책이 놓쳤는지 확정할 수 없다. “GPT가 후보를 못 만든다”와 “gap gate가 대부분 막는다”를 수치로 분해할 근거는 부족하다.

## 2. 전체 브랜치 인벤토리

아래 SHA는 tip이다. 커밋 수는 `git rev-list --count origin/main..origin/<branch>`, 파일 수는 `git diff --name-only origin/main...origin/<branch>` 기준이다. 전송 체크포인트 커밋 수를 독립 실험 횟수로 세지 않는다. `origin/HEAD`는 main의 symbolic ref이므로 14개에 중복 산입하지 않았다.

| origin 이후 브랜치 | tip | main에 없는 커밋 | merge-base 이후 변경 파일 | 내용과 증거 |
|---|---|---:|---:|---|
| docs/current-evidence-and-legacy-20261012 | 714213c | 14 | 153 | 현재 controlled-dev / legacy 주장 범위 정리; 새 LLM 결과 아님 |
| eval/alba-20261027-once | 565c0c6 | 2 | 22 | RAG 단회 실행 계획·UI·검증 구현; 저장 실행 결과는 후속 feat 브랜치에 있음 |
| feat/alba-rag-service-20261027 | 493935f | 3 | 43 | RAG 서비스와 저장 24응답·사후 인용 재검증·브라우저 증거 |
| feat/phase2-independent-evaluation | 564a664 | 12 | 153 | 독립 생성/봉인/평가기; 무료 준비만, 실험 원본 일부 부재 |
| feat/phase2-llm-validation-20261013 | 871af28 | 15 | 184 | 지속 비용 예약·MIRACL 첫12 출처 검수·UTF-8 수정; 실제 호출 0 |
| feat/selective-retrieval-repair-v2 | 3238d58 | 9 | 129 | PR1 controlled-dev 36질의·3정책·trace·v1/v2 분리 |
| main | f3ca14a | 0 | 0 | v1 기본 구현과 후속 연구 요약; 연구 구현 미통합 |
| ops/independent120-v3-20261016 | db00dc5 | 447 | 571 | v3 bootstrap·암호화 runtime/input/checkpoint; 실행 원시 결과 비공개 |
| ops/p2r3-gpt-actions-preflight | cb283a2 | 1 | 1 | 모델 접근 확인 Actions; 후보 생성 성능 근거 아님 |
| ops/p2r3-gpt-continuation-20261014 | cafffad | 61 | 114 | 계속 실행용 봉인 입력·체크포인트 전송; 다수 커밋은 전송 receipt |
| ops/p2r3-gpt-run-20261014 | 9f2ad21 | 15 | 57 | p2r3 단회 실행 bootstrap·암호화 전송, 회귀 테스트 환경 격리 |
| ops/phase2-gpt-provisional-20261014 | ad431ae | 68 | 68 | provisional GPT 승인 배치·암호화 런타임 전송 |
| ops/phase2-miracl-restore-20261014 | ac50e29 | 4 | 4 | hash 고정 문서 복원 및 불일치 진단 보존; 품질 비교 아님 |
| ops/v4-gpt-20261017 | 5d9549e | 487 | 490 | 공개 runtime zip 분할 + 암호화 실행입력/출력·봉인 receipt |

`docs/current...`, PR1, Phase2 브랜치는 연구 작업의 선형 계보를 공유한다. 그 안에 반복 보관된 validation/evaluation/evaluation-final JSON은 서로 다른 held-out 실험이 아니다. ops의 transfer/checkpoint는 후보 생성·전송 단계의 보존 증거이며 최종 점수 검증을 대체하지 않는다.

## 3. 평가 경계·누설·순서 의존성

### PR1과 원래 Phase2: 정답을 쓰는 사후 게이트

- PR1 `src/searchclinic/research/runner.py::run_experiment`는 기본 검색의 observation/detection을 먼저 고정하나, 후보는 `propose_candidates(gate.engine, query)`에서 앞선 채택이 누적된 engine으로 생성한다. 따라서 후보 자체도 질의 순서에 따라 달라질 수 있다. `GateAdapter`는 full evalset/qrels로 채택을 판정한다. `after`는 모든 채택을 누적한 최종 engine으로 전 질의를 다시 평가한 값이다.
- Phase2 `evaluator.py::_run_arm`도 `run_gate(engine, evalset, rx)`에 최종 정답을 전달하며 채택하면 `engine=sandbox`, 첫 채택에서 중단한다. 세 arm은 각자 새 engine으로 시작하지만 arm 내부는 고정 질의 순서의 누적 수정이다. 생성기를 일회 봉인했으므로 후보 생성기로 정답이 직접 돌아가지는 않으나, **최종 설정 선택에는 평가 정답이 들어간다**. 이는 label-assisted diagnostic이다.
- Phase2 `_load_labels`는 label SHA, 질의 순서·coverage, corpus/evidence 대응을 검사하고 `_preflight`는 양 arm 봉인·source·protocol·manifest를 재검증한다. 이런 경계는 유용하나, gate가 쓰는 정답을 독립 validation/test로 분리하지 않는다. 생성기 분리와 테스트 정답 비사용은 별개의 조건이다.
- Phase2 실제 비교 경로는 `evaluate_bundle(..., synthetic_only=False)`에서 명시적으로 `PermissionError`를 발생시킨다. 해당 두 공개 개발 브랜치만으로 유료 LLM 실험이 완료됐다고 보고할 수 없다. `PHASE2_FINAL_REPORT.md`도 실제 호출 0·비교 미실행으로 기록한다.

### v3와 v4 primary: 정답 없는 적용 뒤 채점

v4 archive에 포함된 `vendor/independent_v3/blind.py::apply_arm`는 label-free이지만 앞선 수정을 전체 engine에 누적하고 마지막 설정으로 모든 순위를 산출한다. 순서와 전역 교차영향은 남는다. 같은 archive의 `independent_v3/diagnostic.py`는 명시적으로 `retrospective_label_assisted_diagnostic`이며 Phase2 `_run_arm`을 재사용한다. README의 v3 primary GPT 0.7150100과 사후 gate 0.7259를 혼용하면 안 된다. 다만 **이 vendored v3 코드가 원래 v3 실행 runtime과 바이트 단위로 동일하다는 검증은 현재 못 했다**. 원래 v3 runtime은 암호화돼 있다.

v4 `repair_execution/apply.py`는 후보를 원시 응답으로 재구성·검증한 뒤, 보호 경로·evaluator import 차단을 둔 자식 프로세스에서 적용한다. `repair_v4.py::apply_scoped`는 질의마다 `engine=base`에서 시작해 해당 질의에만 설정을 적용한다. 한 후보 실패 시 다음 후보로 재시도하지 않는다. `repair_execution/evaluate.py::evaluate_primary`는 순위 seal/hash와 labels SHA를 확인한 다음에 정답을 읽는다. 이는 Phase2 정답 gate와 구분되는 재사용 가치가 있는 경계이다.

프로세스 경계는 코드 주석대로 **신뢰한 Python worker의 실수 방지용**이다. `-I`, 환경 축소, audit hook은 적대적 Python에 대한 OS sandbox가 아니다. 문서·질의가 공개 벤치마크인 만큼 모델 사전학습 노출 여부도 확정하지 않는다. 60/60 정상·실패로 고른 judged-pool 표본은 case-control 성격이며 실제 트래픽 실패율·전체 MIRACL 코퍼스 성능을 대표하지 않는다.

## 4. v4 후보·정책 병목

공개 README의 보존 요약은 73회 생성, 63/73 **후보 목록** 규약 통과, 10 실패, 실제 적용 2건이다. 63을 유효한 개별 후보 수나 효과 있는 수정 수로 읽지 않는다. 두 적용의 ΔnDCG는 +0.2262와 −0.2262로 상쇄됐다. 정상에 적용한 후보가 0이므로 정상 회귀 0은 안전성의 실증이 아니다. 이 숫자는 원시 결과로 새로 재계산한 값이 아니다.

코드가 보여주는 잠재 병목은 다음과 같다. 실제 발생 건수는 비공개 실행파일 없이는 미측정이다.

1. **근거 접근 한계**: `context_v4.py::build_context`는 baseline search/grep/similar 순으로 문서를 최대 10개 고르고 정해진 길이의 excerpt만 제공한다. 올바른 수정 어휘가 문맥에 없으면 literal evidence 검사로 생성 불가능하다. query는 256자를 넘으면 자르지 않고 거부한다. `supported_context`는 원문에 없는 similar token을 제거하며 literal catalog는 32토큰까지만 보여 준다.
2. **행동 공간 한계**: user word / synonym / compound만 가능하다. 질문에 답하는 문서가 BM25에 낮게 뜨는 문제, 의미 검색·rerank가 필요한 문제는 이 schema로 고칠 수 없을 수 있다. literal 동시 등장만으로 의미 동등성을 증명하지도 못한다.
3. **규약 손실**: target_query 완전 일치, case-sensitive contiguous evidence, compound 부분 이어붙임 등의 구조 제약이 있다. v4 `validate_list`는 잘못된 후보만 버리고 정상 sibling 순서를 보존한다. envelope가 잘못되거나 세 후보를 넘으면 목록 전체 실패이다. 빈 목록의 의도적 abstention과 모든 후보 무효는 다른 상태이다.
4. **gap gate의 보수성**: `repair_v4_policy.py::candidate_gap`는 문맥 전체 문서 토큰 합집합 dt를 쓴다. synonym은 qt−dt anchor와 dt−qt target이 모두 있어야 한다. anchor가 무관한 한 문서에만 나타나도 해당 lexical gap이 없어질 수 있다. 모든 patch component가 조건을 통과해야 해서 혼합 후보 하나의 부적합 요소가 전체를 막는다. 이 조건은 의미 동등성도 보장하지 않는다.
5. **선택 순위 한계**: `policy.py::select_action`의 utility는 동일 질의의 공통 탐지확률·min_gain·선언 비용에 의해 결정된다. 동일 비용 후보끼리는 효과 예측 점수가 같아 첫 후보가 선택된다. gap 통과 후 한 후보만 적용하므로 더 좋은 두 번째 후보의 이득을 탐색하지 않는다. 채점 없는 “first eligible”와 정답을 이용한 “oracle best”를 분리해서 비교해야 한다.

다음에 필요한 퍼널은 query별 `detected → attempted → response confirmed → empty / content error / partial valid / valid → gap eligible → selected → structural success → ranking changed → positive/negative/zero Δ`이다. 후보별 raw index, rejected reason, sibling survival, gap checks도 함께 남겨야 63→2를 설명할 수 있다.

## 5. hash·출처 검사

공개 v4 runtime zip의 검증된 archive SHA256은 `ddd908f1bf9a84f1b9b32d00697afa9835bb2c2a25141203add9ce0aea316e77`이다. 이번 감사에서 추출된 `RUNTIME_V4_MANIFEST.json`의 **120개 파일 hash를 모두 대조했고 불일치 0개**였다. `plan.py::source_identity`와 같은 src + repair_execution + vendor 범위로 파일별 hash map을 만들고 digest한 결과도 `EXPECTED_SOURCE.json`의 `efa3296f03a578d5bd58837f7b528c687f4f4b71c846f5fe902c88bc357dae06`와 같았다. dependency version은 실행 환경과 별도 확인이 필요하며 이 정적 검사가 runtime 입력/응답의 복원을 뜻하지 않는다.

Phase2 `contracts.py::source_provenance`의 source_hash는 src 전체 문자열 map을 digest한다. 새 파일 하나를 넣어도 hash가 달라지며, source_dirty는 src/tests만 대상으로 한다. v4 identity는 별도 범위의 **파일 바이트별 SHA map**과 dependency 버전이다. 두 hash는 계산 방식·대상부터 다르므로 서로 비교할 수 없다. 통합 브랜치의 현재 hash로 과거 seal을 덮어쓰지 않는다. 원래 source/protocol/dependency를 보존한 별도 replay manifest를 만들고 새 결과에 새 계보를 붙여야 한다.

Phase2 `load_protocol`은 현재 파일을 pre-outcome commit `921ce4b...`와 비교하므로 통합 후에도 그 Git object가 필요하다. v4 archive는 `contains_git_history=false`, `contains_research_inputs=false`다. 단순히 zip만 복사하면 모든 과거 실행 계약이 충족된다고 보장할 수 없다. main에 이미 있는 코드와 이름이 같은 파일도 그 내용이 같다고 가정하지 않는다.

## 6. 실패 처리

Phase2는 full query coverage, 임의 필드 거부, literal span 재검사, write-once 출력, label commitment, durable SQLite reservation 등을 준비했다. 비용 예약은 실패 시 사라지지 않아 미결 호출을 0회로 오인하지 않는다. Windows UTF-8 worker 수정은 실제 boundary 테스트를 통해 기록됐다. 단 이 준비 코드는 실제 공급자 응답 검증 성공의 증거와 구분한다.

v4 `repair_v4_response.py::parse_response`는 HTTP/model/usage/finish_reason/refusal/토큰 상한의 불명확한 실패에서 전체 실행을 중단한다. 응답 usage가 확인된 내용 오류만 terminal content error로 보존하고 다음 질의로 간다. 후보별 구조 오류는 candidate audit에 남겨 정상 sibling을 살린다. `runtime.py::execute`는 호출 전에 attempt와 checkpoint를 남기고 raw bytes→meta→receipt→seal 순서로 저장한다. 재시작·자동 retry/resume을 허용하지 않으며 unknown transport를 무과금 성공으로 바꾸지 않는다. 실패 시 `incomplete.json`을 남기고 최종 후보 seal을 제거한다. `validate_bundle`은 원시 응답에서 receipt/후보/비용을 다시 계산해 저장 seal과 비교한다.

v3 `ops/bootstrap_v3.py`는 generation 종료 여부와 무관하게 generation.log 및 출력 디렉터리 terminal snapshot을 암호화 보존한다. 출력 ciphertext의 존재·checkpoint 완료는 보존 절차의 근거이고, 정답/후보 품질 자체의 근거는 아니다.

## 7. 실제 접근 가능한 개발 자료와 제한된 oracle

### PR1 저장 trace 재집계

재집계 원본은 `origin/feat/selective-retrieval-repair-v2`의 `artifacts/research/versions/phase01-v2/evaluation-final/runs/` 아래 세 JSON이다.

- `no_repair-20261012T062827-22b7e47a.json`
- `always_typed_patch-20261012T062838-51deca4a.json`
- `selective_rule-20261012T062839-7de30bb4.json`

모두 controlled-v1/dev, 36질의, 원시 본문/정답은 기존 catalog/evalset에서 재구성 가능하다. 원래 source `73a9fcc...`, corpus hash `0fc66c40b278ec0f8a357f177a1db3945581da9776043c0532ce663281aef62f`, evalset hash `4163f6921755ade3c8ca03b579bc6e3b272c34c0b14a0ce59fd3a192569e386f`가 기록돼 있다. Kiwi 0.23.2를 사용했으며 RAG24의 0.24.1과 섞으면 안 된다.

| 정책 | 탐지 실패 | 진단 질의 | 제출 질의 / 후보 | 채택 질의 | 실패 개선 | 정상 최종 회귀 |
|---|---:|---:|---:|---:|---:|---:|
| No Repair | 23 | 0 | 0 / 0 | 0 | 0/16 | 0/20 |
| Always | 23 | 36 | 14 / 15 | 11 | 11/16 | 0/20 |
| Selective | 23 | 23 | 12 / 13 | 11 | 11/16 | 0/20 |

Selective 탐지는 TP14/FP9/FN2/TN11이다. 실패 진단을 건너뛴 두 건과 후보를 생성하지 못한 실패는 구분해야 한다. trace에는 **제출된 후보**의 prescription/evidence/gate target_before/after가 있지만 첫 채택 이후의 미제출 ladder suffix는 없다. 따라서 “모든 생성 후보 oracle”은 계산할 수 없고 **실제로 제출돼 저장된 후보의 관측 최대 이득**만 집계할 수 있다. 아래 최대 Δ는 각 저장 trace의 gate 직전 누적 engine에서 측정한 값으로, 공통 pristine baseline에 각각 적용한 독립 oracle이 아니다. 선택 정책 비교나 v4 수치를 대체하지 않는다. `—`는 관측된 제출 후보 없음이며 oracle 이득 0이라는 의미가 아니다.

표의 A=Always, S=Selective. 제출은 trace 개수, 채택은 해당 질의의 boolean, 최종은 전체 누적 설정의 nDCG, 최대Δ는 저장된 후보 gate target_after−target_before의 최댓값이다. gate에서 기각된 정상 후보의 음수 Δ도 그대로 보존했다.

| 질의 | 초기 nDCG | A 제출 | A 채택 | A 최종 | A 관측 최대Δ | S 제출 | S 채택 | S 최종 | S 관측 최대Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 프라이팬 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 케이크 | 1.0000 | 1 | 0 | 1.0000 | -0.1228 | 1 | 0 | 1.0000 | -0.1228 |
| 도넛 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 주스 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 소시지 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 어댑터 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 물티슈 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 샤인머스캣 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 트레이닝복 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 휴대폰 거치대 | 0.9639 | 0 | 0 | 0.9639 | — | 0 | 0 | 0.9639 | — |
| 무선 이어폰 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 노트북 파우치 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 팬미팅 굿즈 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 선풍기 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 캠핑 의자 | 0.9448 | 0 | 0 | 0.9448 | — | 0 | 0 | 0.9448 | — |
| 운동화 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 카펫 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 리모컨 | 1.0000 | 0 | 0 | 1.0000 | — | 0 | 0 | 1.0000 | — |
| 가습기 | 1.0000 | 1 | 0 | 1.0000 | -0.3691 | 0 | 0 | 1.0000 | — |
| 김치 | 1.0000 | 1 | 0 | 1.0000 | +0.0000 | 0 | 0 | 1.0000 | — |
| 후라이팬 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 케잌 주문 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 도너츠 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 쥬스 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 소세지 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 카페트 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 초콜렛 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 리모콘 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 블루투스 스피커 | 0.5000 | 0 | 0 | 0.5000 | — | 0 | 0 | 0.5000 | — |
| 텀블러 | 0.6131 | 0 | 0 | 0.6131 | — | 0 | 0 | 0.6131 | — |
| 핸드폰 | 0.0000 | 0 | 0 | 0.0000 | — | 0 | 0 | 0.0000 | — |
| 츄리닝 | 0.0000 | 0 | 0 | 0.0000 | — | 0 | 0 | 0.0000 | — |
| 티슈 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 머스캣 | 0.0000 | 1 | 1 | 1.0000 | +1.0000 | 1 | 1 | 1.0000 | +1.0000 |
| 아답터 | 0.0000 | 2 | 1 | 1.0000 | +1.0000 | 2 | 1 | 1.0000 | +1.0000 |
| 백팩 | 0.0000 | 0 | 0 | 0.0000 | — | 0 | 0 | 0.0000 | — |

양 정책에서 양의 관측 최대Δ가 있는 실패는 11건이며 실제 채택 11건과 같다. 이것만으로 후보 선택기가 최적이라고 결론내릴 수 없다. 저장되지 않은 후보, 탐지로 건너뛴 후보, 정답 gate가 막은 회귀, 누적 순서가 모두 검열돼 있다. v5에서 저장 후보를 공통 baseline에 개별 적용한 새 replay를 만들 경우 이는 별도의 사후 개발 진단이라고 명시한다.

### RAG24의 원시 출력과 사후 재검증

`origin/feat/alba-rag-service-20261027:docs/verification/alba-20261027/run/results.json`에는 12 작성 case × retrieved/no_documents의 **24개 context와 raw structured model 출력**, usage·latency, 원래 validator verdict가 있다. 원래 결과는 invalid12 / abstain11 / supported1, gate accepted1이다. `revalidated.json`은 같은 저장 출력을 인용 whitespace/paired bold 정규화로 사후 재검증한 결과이며 새 API 호출 0, invalid6 / abstain12 / supported6, gate accepted4 / rejected2이다. 즉 보정으로 생성 모델이 더 나아졌다는 주장은 불가하다.

이 데이터는 `gpt-5.4-mini-2026-03-17`, 작성 문제설명·진단 문서·citation schema를 쓰는 별도 과제다. v4의 gpt-4.1-mini·MIRACL·literal patch 근거와 합산하지 않는다. 다만 **이미 저장된 출력의 schema/citation failure, patch 보존, gate 조건별 손실을 API 없이 다시 분석할 자료**로 적합하다. 외부 실제 고객 로그나 held-out 일반화 성능이 아니다.

## 8. 현재 열 수 없는 구성요소

| 범위 | 공개로 확인한 것 | 없는 것 / 할 수 없는 검증 |
|---|---|---|
| v3 `runtime/38842054422` | chunk manifest/hash, bootstrap, 암호문 | 복호화 키 없음; 원래 실행 runtime의 정확한 소스·입력 context·plan을 실행 상태로 복원 불가 |
| v3 `transfer/38842054422` | ready/input/checkpoint-sealed-206 manifest 및 ciphertext | 후보 raw response/receipt, original plan/baseline, 순위 seal, 최종 공식 label·review 결과의 재계산 불가 |
| v4 `ops/v4/runtime.zip.part*` | 공개 zip 소스, 120 manifest 파일 및 source identity 검증 | 연구 입력은 archive에 원래 포함되지 않음 |
| v4 `transfer/39044121771` | input/ready/checkpoint-sealed-221의 hash 및 ciphertext | 복호화 키 없음; query별 생성·오류·gap gate·실제 순위·라벨·63→2 원인 집계 및 후보 oracle 불가 |
| Phase2 8문서/12질의/6집단 pilot | free-preparation-status의 hash·건수·미완료 상태 | 원래 corpus/stimuli/qrels·sealed candidates 없음; 원문/label 재검토와 성능 재실행 불가 |
| Phase2 MIRACL first12 | topics/qrels/source manifest·검수 기록·추출 코드 | 공개 Git tree에 원문 corpus shard가 없음; 현재 사본만으로 full exact reconstruction 불가. 본 감사는 다운로드하지 않음 |

암호문을 원시 후보가 있는 것으로 취급하거나 누락된 점수를 0으로 채우지 않았다. README의 v3/v4 최종 수치는 보고된 집계로만 인용하고 새로 검증된 per-query 결과로 재명명하지 않는다.

## 9. v5 재사용 권고

1. PR1/Phase2를 연구 모듈로 복원하되 기본 CLI·공개 v1 지표와 분리하고, 원래 프로토콜 파일·commit object·artifact를 그대로 보존한다. `*_v2`의 posthoc latency 비용 수정도 v1 결과를 대체하지 않게 유지한다.
2. v4의 개별 후보 validator, sibling 오류 audit, full raw→receipt reconstruction, exact-query scoped application, labels-open-after-ranking-seal 구조를 독립 모듈로 가져온다. 유료 승인·GitHub 전송·암호화 bootstrap까지 기본 실행 의존성으로 만들 필요는 없다. source identity와 새 replay manifest를 별도로 기록한다.
3. 먼저 PR1 저장 trace와 RAG24 raw만으로 오프라인 개발 replay를 만든다. query 단위 funnel과 후보별 사유를 보존하고, first eligible·label-free 선택·정답 oracle을 서로 다른 산출물로 둔다. oracle은 API 호출 없이 고정된 저장 후보에만 적용하며 unseen top-3 후보를 만들어 보충하지 않는다.
4. 성능 평가용 라벨은 모델/선택기/threshold 개발에 사용한 자료와 분리한다. 전역 analyzer 수정을 다시 평가한다면 고정 순서 한 번만으로 끝내지 말고 pristine per-query 적용과 여러 순서의 교차영향을 별도 분석한다. v4 exact-query 정책은 순서 혼입을 줄이지만 전역 배포 성능의 대용은 아니다.
5. v4 과거 실행의 exhaustive funnel/oracle은 원래 소유자가 이미 복호화한 합법적 파일을 제공하는 경우에만 추가한다. 필요한 최소 자료는 고정 plan·baseline context/documents, raw response/receipt/candidate audit, application_gate/decision/rankings seal, 공식 label 및 그 hash이다. 현재 자료 부재를 모델 호출로 메우지 않는다.

## 10. 감사 재현 범위

브랜치/commit/file 인벤토리는 Git의 `for-each-ref`, `log`, `ls-tree`, `show`, `diff`로 읽었다. PR1/RAG24 집계는 위 JSON의 query/row/trace 상태를 직접 세었고 PR1은 기록된 gate target_before/after만 뺐다. v4는 archive manifest의 각 파일 SHA256과 plan source_identity 대상의 canonical JSON digest를 재계산했다. 구현 테스트나 새 검색 성능 실행은 이번 문서 감사의 범위가 아니며, 여기의 검증 통과는 정적 hash/저장 JSON coverage에 한정한다.
