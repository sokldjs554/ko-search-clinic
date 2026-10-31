# ko-search-clinic 후속 검증 보고서 · 2026-10-30

**판정: 새로운 독립 평가에서 RulesPlus·No Repair 대비 우위는 아직 입증하지 못했다.** 무료로 가능한 소스 감사, 통합, 수정, 저장 후보 재실행과 검증 경로를 구현했다. 유료 판정 호출, 복호화 자료, 독립 정답 검수는 확보되지 않았으며 이를 완료로 표시하지 않는다. 대학원 제출 당시 v4와 구분되는 **제출 이후 추가 연구**다.

[2026-10-31 실제90회 호출 결과와 새로운 원인 분석](LIVE_EXPERIMENT_20261031.md)을 별도 보존했다. 이 문서는 이전 개발 기록이다.

2026-10-31 후속 구현·무료 기준선·새 자료 상태는 [별도 후속 보고](FOLLOWUP_20261031.md)에 기록한다. 아래 수치와 서술은 10월30일 개발 진단 기록이다.

## 1. 기존 문제와 조치

| 문제 | 확인 근거·관련 파일 | 이번 조치·남은 조건 |
|---|---|---|
| main Kiwi 분석 실패 | 양 OS CI `40650843416`, `analysis/analyzer.py` | PR2의 Kiwi0.24.1/model0.24.0/cong-global 재사용. 포도 테스트 RED→GREEN, baseline 보존 |
| 전체 평균 하락 허용 | `patch/gate.py`가 epsilon0.02를 평균에도 사용 | 평균 tolerance1e-12 분리, 전체 정밀도 metric으로 판정. 표적0.05/질의별0.02 유지 |
| 평균 반올림으로 손실 은폐 | 보고 평균뿐 아니라 개별 metric도4자리 반올림 | `evaluate_query/evaluate_all(round_metrics=False)` 추가, gate만 사용. 기본 metric 반환과 기존 artifact 보존 |
| 평가 정답이 채택에 영향 | 초기 `phase2/evaluator.py` gate와 누적 engine | legacy 진단으로 유지·문서 명시. 새 선택에는 qrels 없이 exact-query 독립 적용 |
| 간접 정답 모듈 import | corpus/patch `__init__` eager import | lazy exports로 기존 public API 유지, fresh subprocess에서 label/evaluator 미로딩 확인 |
| 후보 의미 검증 없음 | v4 lexical presence/gap는 동의관계 미검증 | pair/context/rubric 요청·구조화 판정·원문 위치 검증·후보/문맥 hash/model 결합 구현. 실제 판정 품질 미측정 |
| 잘못된 후보 때문에 형제 후보 손실 | 초기 전체 목록 validation | v5는 후보별 검사, 원래 index 보존; malformed/누락/실패 보류 이유 기록 |
| 생성 실패 기록 누락 위험 | 진단에 후보0이면 실패와 abstain 구분 안 됨 | diagnostic 및 요청 export에 질의별 generation_error 보존; 실패 후보 재적용·자동 재시도 안 함 |
| 누락·중복·모호한 qrels | 평가 입력 경계 | 전 질의 coverage, rank중복, null정답, finite값, split문서/개념 중복 검사 |
| PR2 main 충돌·기능 분산 | PR1/Phase2/PR2 diff | 최신main 기반 파일 단위 통합. 기존Draft/ops원본·커밋 보존, 유료workflow/대형전송 archive 제외 |
| RAG 재검증 원본 덮어쓰기 | `scripts/revalidate_alba.py` | 새 출력 디렉터리만 허용, 역사적 결과 경로 보호, 재실행 거부 테스트 |
| CI console pytest에서 스크립트 import 실패 | 초기 양 OS 실행41043173402, 준비 테스트6건 | 파일 경로로 테스트 대상 로드, console pytest로 RED→GREEN 검증 |
| README와 실제 기능 불일치 | main과 별도 브랜치 설명 혼재 | v5·v3/v4·RAG 구분, 연구 진단 화면을 기존 데모에 연결 |

[14개 브랜치 상세 감사](AUDIT.md), [통합 파일 출처](integration-sources.json), [GitHub 조회 기록](github-audit.json).

## 2. 원시자료와 v4 퍼널 복원 범위

공개 v4 runtime archive SHA256 `ddd908f1bf9a84f1b9b32d00697afa9835bb2c2a25141203add9ce0aea316e77`을 확인해 소스를 복원했다. 내부 manifest120파일과 source identity도 일치했다. 암호화된 결과 artifact의 존재·만료여부·digest는 조회했지만 **복호화하지 않았다**.

| 단계 | 확인 가능한 값 | 질의별 원인·ID |
|---|---:|---|
| v4 생성 | 기존 보고73건 | 원시값 미복원 |
| 규약 통과 / 실패 | 기존 보고63 /10 | JSON/Pydantic/빈 후보 분해 불가 |
| 실제 적용 | 기존 보고2건 | gap/정책/의미별 탈락 수 미복원 |
| 개선 / 악화 | 기존 보고1 /1 | 각각 +0.2262 /−0.2262, ID 미확인 |

따라서 문자열·의미·탐지·선택·회귀별 숫자를 임의 배분하지 않았다. v4는 정답 gate로 후보를 채택하는 초기Phase2와 다른 경로이므로 “61개가 회귀 gate 때문에 탈락” 같은 해석도 하지 않는다. 초기 파일럿 노출 목록이 없어 과거자료와 새자료의 완전한 비중복도 미검증이다.

## 3. 실제 실행한 개발 진단과 Oracle

PR1 trace의 **실제 제출 후보15개 / 가용14질의 / 전체36질의**를 현재 엔진 pristine baseline에 각각 적용했다. 저장집합 자체가 과거 진단·정책·정답 gate 중단에 영향을 받았고 미제출 후보는 누락돼 있다. 이 Oracle은 **관측된 부분집합 조건부 진단 상한**이다.

| 조건 | 전체 nDCG@10 | 실패 nDCG@10 | Recall@10 | Precision@5 | 실패 개선 | 정상 회귀 |
|---|---:|---:|---:|---:|---:|---:|
| 수정 없음 | 0.5839426551 | 0.0695716995 | 0.5972222222 | 0.2000000000 | 0 | 0 |
| 저장 첫 후보 | 0.8492385035 | 0.6945716995 | 0.8750000000 | 0.3166666667 | 10 | 2 |
| 관측 후보 Oracle + noop | 0.8894982106 | 0.7570716995 | 0.9027777778 | 0.3277777778 | 11 | 0 |

첫 후보 대 baseline 평균차 +0.2652958484, 95% bootstrap 구간 [0.1252044743,0.3795859847]. 이는22개 사후 정답문서중첩군의 기술 통계다. 독립 검수 개념군·미공개 데이터가 아니므로 양의 구간을 일반화나 새방법 우위로 주장하지 않는다.

동일14건 적용 random100은14개 가용질의 모두를 골라야 하므로 후보2개가 있는 한 질의만 변한다. 평균차0.2777958484, 범위[0.2652958484,0.2930736262]. 이 제한을 숨기지 않는다. 유용후보11개는 두 gate 진단 모두 채택하며 유용후보 기각0이다. 이 자료에서는 “회귀 gate가 지나치게 보수적”이라는 가설이 지지되지 않았다. 완전한 후보집합이나 v4에 이 결론을 확대할 수 없다.

상세 JSON·CSV는 공개 승인 전까지 로컬 보존하며 README의 무료 명령으로 재현한다. API0회, API비용$0, 검색576회·색인16회. wall time은 각 실행의 JSON에 실측한다. 현재 지표는 fixed denominator Precision@5와 전체정밀도 nDCG를 쓰므로 과거 수치와 단순 비교하지 않는다.

실제 실패 사례: 첫 후보 적용에서 정상 질의가2건 악화됐다. `아답터`의 저장 후보는2개로 첫 후보와 Oracle 선택 차이가 난다. 각 질의의 정확한 전후 순위·지표·처방과 gate 사유는 로컬 CSV/JSON 및 상세 데이터를 로드한 로컬 데모에서 확인한다. 의미 관계를 이 사후 결과만으로 판정하지 않는다.

## 4. 새 방법의 기술적 기여와 검증 범위

`research_v5/semantic.py`: 같은 후보를 pair/context/rubric 조건으로 준비하고, 동의·상하위·범주/값·불확실 관계, 동일 대상·범위 유지·근거, confidence, 인용 위치를 구조화한다. 모든 patch가 판정돼야 하며, 후보·질의·모델이 바뀌거나 원문 인용이 맞지 않으면 보류한다. confidence의 minimum으로 보수적으로 순위를 정하되 개선 확률로 해석하지 않는다.

`pipeline.py`와 CLI: 공개입력 whitelist, 후보별 형식·literal검사, 오류 보존, exact-query격리, hash봉인, 분리채점, 소스/분석기 변경 거부. `evaluation.py`: 완전coverage, fullprecision지표, clusterbootstrap, 유용후보미선택, matched-count random, split중복검사.

로컬에 실제 생성한 준비물은 `artifacts/research/v5-prepared/` (공개 변경에서 제외): 36질의/15후보, 세 조건 요청, 빈 판정 파일, 분리된 개발 정답, 비용 제안. 빈 판정으로 apply→score를 실행해 누락판정이 전부 보류됨을 확인했다. 이는 실험 인프라의 fail-closed 검증이며 새방법 성능 평가로 세지 않는다. 실제 모델 판정·세조건비교·효과적 ablation 결과는 없음.

## 5. 테스트·CI·재현

검증 로그는 [verification](verification/)에 보존한다. 수정 커밋 `fd073c5`의 [원격 CI](https://github.com/sokldjs554/ko-search-clinic/actions/runs/41043768505)는 Ubuntu·Windows 각각 **561 passed, 2 skipped**, 검색 품질 게이트 성공이다. 첫 실행의 준비 테스트 경로 실패도 숨기지 않고 보존했다. [통합 Draft PR #3](https://github.com/sokldjs554/ko-search-clinic/pull/3)에서 최신 문서 커밋의 checks도 확인할 수 있다. Kiwi 기존 실패, gate 평균손실/정밀도 실패와 수정 후 통과를 기록했다. Linux 전체 pytest, baseline, offline prepare/apply/score, 실제 headless Chromium에서 연구36질의·3비교군·1440/320/390px·RAG replay와 JS오류를 검사했다. 최종 테스트 수와 원격 CI URL/SHA는 `verification/final-status.json`을 기준으로 한다. 초기 통합540pass 기록보다 뒤의 수정이 있으므로 초기 수치만으로 최종 완료를 주장하지 않는다.

의존성은 `requirements/ci-py311-312.txt`; 역사적 Kiwi0.23.2 환경은 별도보존이다. 기본 36질의 baseline 평균0.5839가 유지됐고 `docs/BASELINE.json`은 그대로다. 선택적 PostgreSQL/규모(PyArrow) 테스트는 설치하지 않은 의존성 때문에 skip되며 해당 외부서비스 성공을 주장하지 않는다.

브라우저 재현:

```bash
python -m http.server 8765 --bind 127.0.0.1 --directory src/searchclinic/web
# 별도 터미널, playwright와 Chromium 설치 후
node scripts/check_v5_browser.cjs work/browser http://127.0.0.1:8765
```

## 6. 미완료 항목과 필요한 입력

| 항목 | 정확한 차단 원인 | 다음 단계 |
|---|---|---|
| v3/v4 질의별퍼널·완전Oracle | 원시자료 암호화, 키/복호화본 없음 | 권한 있는 복호화본 또는 안전한 키 경로 확보 후 동일 hash 검사 |
| 실제 LLM 의미 검증 | 새로운 유료호출 승인 없음, 키 사용방식 미결정 | 고정90회/$0.72 개발실험 제안 별도승인, 모델접근성 확인 |
| 새 independent final | 새정답·문서/개념검수·외부판정자 없음; 과거120노출목록도 불완전 | 새자료와 독립검수·중복확인 완료 후 최종프로토콜 동결 |
| 4개 주요군 우위 및 통계 | 위의 실제실험이 미실행 | 실패·모호함도 보존하며 동결자료 한 번 채점 |
| RFL | 검수된 충분한 판정/근거 학습자료 없음 | 먼저 의미검증 병목 확인 후 별도 타당성 검토 |

이번 버전을 전체 연구 목표의 최종 완성이라고 표시하지 않는다. 유료/API 연결이 필요한 작업만 보류했으며 원본 실험과 기존 Draft PR은 보존했다.

## 7. 면접에서 정확히 설명할 수 있는 추가 성과

“기존 v4에서는 평균 우위가 없었습니다. 후속 작업에서 후보의 형식 준수, 의미적 타당성, 실제 검색 효용을 별도 계약으로 구현했습니다. 저장 후보를 공통 기준 엔진에 개별 적용해 개선 가능한 후보와 정상검색 악화를 확인했고, 이 개발자료에서는 gate 과잉 기각 가설이 지지되지 않았습니다. 정답 누수·누적설정·분석기 버전·반올림 문제를 분리해 검증 경로를 만들었습니다. 독립 데이터와 실제 의미 판정 비교는 아직 필요합니다.”

두 참고논문은 원문을 읽고 과제 차이를 [프로토콜](PROTOCOL.md)에 설명했다. 논문의 성능이 동의어검증에서 재현된 것처럼 말하지 않는다. 코드/문서/분석은 Codex 지원으로 작성했으며 독립 코드리뷰는 AI 검토이지 독립 정답 검수자가 아니다.

## 공개 범위 확인

GitHub 자동 승인 검토가 새 private 정답 파일과 상세 개발 CSV의 공개를 각각 거부했다. 정답·stratum·concept metadata 및 질의별 연결·처방·근거에 대한 별도 공개 승인 부재가 이유다. 같은 내용이 포함된 준비물과 상세 JSON·데모 데이터도 공개 변경에서 제외하고 gitignore 처리했다. 코드는 보존하며 로컬 재현 명령으로 생성할 수 있다. 공개 데모는 실제 집계 결과만 표시하고, 상세 데이터가 로컬에 있을 때만 질의별 화면을 활성화한다. 기존 공개 자료의 원본 파일은 출처 커밋을 유지했다.
