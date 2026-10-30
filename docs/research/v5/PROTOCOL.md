# v5 프로토콜 · 제출 이후 후속 연구

## 현재 단계와 실행 순서

현재 구현·실행된 것은 무료 코드 검증과 **이미 관측한 개발 자료의 사후 진단**이다. 새 독립 최종 평가와 LLM 판단 비교는 미실행이다. 이 파일은 사후 개발 분석과 앞으로의 확증 실험을 구분한다. 기록 날짜: 2026-10-30.

1. 원자료·문서·질의·후보·코드·모델·입력 조건·임계값·예산을 고정한다.
2. 공개 입력에는 질의와 원문 근거, 고정 후보만 넣는다. 정답, healthy/failure, 최종 점수, gate 채택 피드백은 넣지 않는다.
3. 같은 후보마다 pair/context/rubric 요청을 만든다. 모델 ID, 후보 해시, 문맥 해시, 조건, 프로토콜을 판정과 결합한다.
4. 생성 실패·빈 후보·형식 오류·근거 오류·의미 보류·선택·적용을 모든 질의 ID에 남긴다. 유효 후보의 형제 후보가 잘못돼도 함께 버리지 않는다.
5. 최종 순위를 봉인하고 별도 명령에서만 정답을 읽어 채점한다. SHA256은 변경 탐지용 commitment이며 서명이나 사전등록 증거가 아니다.

## 현재 실행 가능한 무료 명령

```bash
python scripts/prepare_v5_development.py --out work/v5-prepared
python -m searchclinic.research_v5 verify work/v5-prepared/candidates.json
python -m searchclinic.research_v5 probe --protected-root work/v5-prepared/private/labels.json
python -m searchclinic.research_v5 apply work/v5-prepared/candidates.json \
  --verdicts work/v5-prepared/verdicts-empty.json \
  --protected-root work/v5-prepared/private \
  --out work/v5-prepared/empty-verdict-application.json
python -m searchclinic.research_v5 score work/v5-prepared/empty-verdict-application.json \
  --labels work/v5-prepared/private/labels.json \
  --out work/v5-prepared/empty-verdict-scores.json
```

빈 판정 파일은 **누락 판정을 보류하는 안전 동작 검사**다. 모델 실험이나 보류 정책의 성능 우위가 아니다. 실제 외부 판정 파일을 넣을 때는 `SemanticVerdict`의 조건·해시·모델과 모든 patch의 assessment를 충족해야 한다. `requests` 명령으로 조건별 요청을 내보낼 수 있지만 네트워크 호출은 구현에 포함하지 않는다.

`--policy first_valid`는 의미 검증을 제거한 구성요소 제거 조건이다. `--condition pair`는 근거 문맥을 제공하지 않는 약한 조건이며 `context_supported=null`과 인용 없음으로 명시한다. 문맥/rubric 조건은 각 patch의 exact quote와 Unicode code-point 위치를 확인한다. 인용의 존재·판정 schema는 실제 의미 판단의 정확성을 보증하지 않는다. 후보를 점수순으로 선택할 때는 모든 수정 요소 confidence의 최솟값을 사용하며 동률은 원래 후보 순서를 따른다. 0.8 임계값은 현재 공학적 기본값이며 보정된 개선확률이 아니다.

실제 application은 원래 엔진에서 각 질의별로 출발한다. qrels 기반 `run_gate`는 최종 선택 경로에 없다. legacy `searchclinic.research.phase2.evaluator`는 정답 기반 사후 진단으로 보존했다. import를 통한 간접 label 로딩을 막기 위해 corpus/patch의 public exports를 lazy import로 바꿨다. 보호 파일 경로와 evaluator import 거부는 신뢰된 프로젝트 코드용 경계다. 악성 Python에 대한 OS sandbox라고 주장하지 않는다.

출력은 write-once다. 실행을 반복할 때는 새 디렉터리를 사용한다. 소스·분석기 fingerprint가 바뀌면 이전 application의 채점은 거부되므로 변경 전 상태를 checkout하거나 새 application을 만들어야 한다. 과거 산출물을 덮어쓰지 않는다.

## 저장 후보 개발 분석의 정의

`replay_saved_development.py`는 PR #1의 두 저장 trace에서 **실제 제출된 후보**를 읽는다. 현재 고정 Kiwi/코퍼스를 사용해 각 후보를 pristine baseline에 적용하고 36질의 전체 영향을 별도로 계산한다. 해당 질의에서 첫 저장 후보를 적용한 조건과, 수정하지 않음을 포함한 최선 후보를 선택한 사후 Oracle을 제공한다.

선택 집합은 과거 진단·정책·정답 gate 중단에 영향을 받았다. 미제출 ladder suffix는 없다. 따라서 전체 생성 모델의 Oracle 상한, 현재 RulesPlus 전체 알고리즘, GPT, 새 의미 선택기와 동일시할 수 없다. 기존 원시 trace의 누적 엔진 점수와 새 독립 적용 점수를 구분한다.

- 전후 nDCG/Recall/Precision 및 정상 질의 악화를 저장한다.
- 정상 회귀는 어느 지표든 감소 >0.02, 실패 개선은 nDCG 증가 ≥0.05이다.
- gate 진단은 표적 이득 0.05, 질의별 epsilon 0.02를 고정하고 평균 tolerance 0.02와 1e-12를 비교한다. 이는 선택기 평가가 아니라 사후 gate 원인 분석이다.
- 100개 seed의 무작위 조건은 적용 질의 수를 정확히 일치시킨다. 현재 14개 적용/14개 가용 질의이므로 실질 변동은 한 질의의 두 후보 선택뿐이다.
- 코드의 실제 gate는 전체 정밀도 점수로 판정한다. 기존 `evaluate_query`의 기본 반올림 반환과 기존 baseline artifact는 보존한다.

## 새 독립 평가의 입장 조건 — 아직 충족하지 않음

기존 상품 36질의, MIRACL 파일럿, v3/v4 120질의는 모두 개발/오류분석 자료로 취급한다. 새 최종 자료로 재사용하지 않는다. 기존120의 원본 ID·문서/개념 목록까지 복원하지 못해 전체 과거 노출과의 비중복을 확인할 수 없다.

새 자료는 train/dev/validation/final의 query_id, 정규화 질의, document_ids, concept_ids를 갖춰야 한다. `evaluation.audit_splits`로 NFKC·공백·대소문자 정규화 중복, ID 중복, 교차 문서·개념 중복을 검사한다. 이 검사는 **지정된 concept_id의 일관성**만 검사하므로 의미상 같은 개념의 별도 ID는 사람이 검수해야 한다. 공유 문서나 개념을 분할 경계에서 분리해 둘 수 없다. 검사 실패 자료를 점수가 좋아지도록 제거해서는 안 된다.

정답표는 문서별 graded relevance와 판정자·판정 시각·근거·모호성 상태를 별도 파일로 관리한다. 가능한 경우 독립2인 판정과 adjudication을 수행하고 원판정을 보존한다. 일치율 및 weighted kappa를 보고하되 실제 판정자가 없으면 값을 계산하거나 독립 검수라고 표시하지 않는다. unresolved/null qrels는 최종 채점에서 조용히 누락하지 않고 오류로 중단한다. 모든 문서·정답·split manifest의 SHA256을 사전 보존한다. 이 저장소에는 아직 독립 검수를 마친 새 final 자료가 없다.

## 확증 비교의 사전 결정 항목

아래는 **최종 데이터와 비용 승인 전 제안**이며, 현재 실행된 확증 프로토콜이라고 주장하지 않는다.

| 항목 | 제안 및 통제 |
|---|---|
| 비교군 | No Repair, 전체 RulesPlus, GPT 기본 선택, rubric 의미 선택, 동일 적용 수 random, pair/context, confidence 제거 |
| 후보 | 생성기 비교와 선택기 비교를 분리. 선택기 비교에서는 candidate bundle 동일 해시 |
| 검색 | 동일 BM25, Kiwi0.24.1/model0.24.0/cong-global, 동일 코퍼스·기본 설정·top10 |
| 입력 | 같은 공개 관측/문서 예산; 정답·성능 피드백 차단 |
| 비용 | 생성·검증 호출을 따로 기록; 총 호출·토큰 예산 일치 추가 비교. pair의 짧은 입력 비용도 공개 |
| 주지표 | 전체 mean nDCG@10, RulesPlus/No Repair 두 기준선 각각의 대응 차이 |
| 보조지표 | 실패 mean nDCG, Recall@10, Precision@5, 실패 개선/정상 악화, 적용/보류, 유용 후보 미선택, 비용·지연 |
| 통계 | 개념군 cluster bootstrap, 고정 seed20261030, 2000회, 95%구간. 최소2군 미만은 구간 미산출 |
| 실질 효과 | 최종 자료를 보기 전에 최소효과와 정상 회귀 허용 한도를 합의·동결. 현재 기본 예시 +0.01은 검증된 효과가 아님 |
| 다중 비교 | 두 주비교의 검정 순서/보정법을 사전 고정; 나머지는 탐색적 분석 표시 |
| 반복 | 동일 후보·입력에 독립 실행 반복; 모델/seed가 보장하는 결정성을 과장하지 않음 |

v5 Precision@5는 항상 5로 나누며 관련성>0만 relevant로 취급한다. nDCG는 점수를 반올림하지 않는다. 과거 짧은 결과수 분모 precision과 비교하지 않는다. 표본 크기·power는 개발 분산과 독립 개념군 수를 확인한 뒤 최종 데이터 개봉 전에 정한다. 현재 개발 구간을 이용해 확증 효과를 주장하지 않는다.

## 실제 LLM 비교 제안과 비용 — 승인 전 미실행

오프라인 준비 파일 `proposal.json`은 저장 후보 15개 × 입력3조건 × 반복2회 = **최대90회**의 개발용 판정 실험을 기술한다. 후보를 다시 생성하는 비용과 새로운 독립 평가 비용은 포함하지 않는다.

- 모델: `gpt-4.1-mini-2025-04-14` 고정. [공식 모델 페이지](https://developers.openai.com/api/docs/models/gpt-4.1-mini)에서 2026-10-30 입력 $0.40/백만, 출력 $1.60/백만을 확인했다. 현재 Deprecated 표시가 있어 실제 계정 접근 가능성은 확인 전이며 임의 대체하지 않는다.
- 호출당 입력 최대12,000·출력 최대2,000토큰, 합계 입력1,080,000·출력180,000토큰, 할인 없는 **최대 $0.72**. 토큰 상한 초과 요청은 잘라서 호출하지 않고 보류한다. 준비 단계의 UTF-8 바이트+여유분은 보수적 상한이며 API 실제 토큰이 아니다.
- timeout/중단/불확실 성공은 해당 호출 최대비용을 예약한 상태로 남긴다. 자동 재시도 없음. 실제 usage와 비용 추정치를 구분하고 영수증이 없으면 청구액 확정으로 쓰지 않는다.
- 보존 증거: 요청 해시·후보 해시·모델 응답 ID·원문 응답·usage·wall time·실패와 예약 원장·조건별 판정·고정 순위·최종 채점 hash.
- 현재 실제 API 0회, 키 사용 방식 미확정, 새 유료 승인 없음. API transport 실행을 추가·활성화하려면 먼저 키 사용 결정을 마치고 이 고정 제안의 별도 비용 승인을 받아야 한다.

## 참고 논문과 RFL 판단

[한양대 NLP 연구실 원문 목록](https://nlp.hanyang.ac.kr/home/publications/dom-conferences)의 PDF를 읽었다.

1. 김민서·이유경·김태욱, 「한국어 LLM-as-a-Judge를 위한 루브릭 전략 비교」, KCC2026. 루브릭 생성 입력(지시문·샘플 응답·인간 선호), 생성 절차, 생성 모델을 비교한 연구다. 본 프로젝트의 pair/context/rubric은 그대로 복제한 실험이 아니라 검색 수정 의미 검증에 맞춘 별도 가설이다. 논문 결과가 이 과제에서 재현됐다고 주장하지 않는다.
2. 손유리·김태욱, 「대화 맥락 추론 향상을 위한 리즈닝 피드백 기반 학습」, HCLT2025. 초기 모델의 오답과 일부 정답에 강한 모델의 설명 근거를 보강해 학습하는 접근이다. 동의어·검색 효용 검증으로의 이전은 미검증이다.

현재는 유효한 독립 semantic label과 충분한 데이터가 없고 저장 후보는15개뿐이다. 별도 학습을 지금 수행하면 자료 편향과 과적합을 키울 가능성이 있어 **RFL 학습은 하지 않았다**. 후속 조건은 개념 분리 학습 자료와 사람이 원문 적합성을 검수한 이유를 확보한 뒤, 동일 base model·사례 수·토큰 예산에서 판정만 학습한 조건과 판정+근거 설명 조건을 비교하는 것이다. 신뢰도는 별도 calibration set에서 평가하고 final에 맞추지 않는다.

공개 저장소에는 새 `private/labels.json`과 label manifest를 포함하지 않는다. `prepare_v5_development.py`를 로컬 새 디렉터리에서 실행하면 공개된 기존 개발 코퍼스로 해당 개발 정답을 생성한다. 새 독립 최종 정답의 공개를 의미하지 않는다.

새 상세 개발 JSON/CSV·요청·채점 산출물도 GitHub 공개 승인 전까지 로컬에 보존한다. 공개 데모에는 집계만 포함한다.
