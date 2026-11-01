# 새 GPT 생성·의미 판정 개발 비교: 실행 전 검증

추가 사람 검수는 중단하고 기존36질의로 연구를 마무리하는 실제 LLM 비교를 준비했다. **새 유료 생성은 아직0회이며, 이 문서는 결과 보고서가 아니다.** 기존90회 승인·실험은 별도로 보존했고 새 승인에 재사용하지 않는다. 현재 판정된 KLUE51쌍은 질문1개에 대한 자료이며 독립 검색 성능을 입증하는 표본으로 쓰지 않는다.

## 실행 내용과 예산

`gpt-4.1-mini-2025-04-14`로 질의당 후보를 한 번 생성한다. 질의당 최대3개 후보를 같은 순서로 Pair·Context·Rubric 각각2회 평가한다. GPT 첫 유효 후보, No Repair, 같은 문맥을 쓰는 RulesPlus, 적용 수를 맞춘 Matched Random을 함께 비교한다. 생성기 표본은1회이므로 두 의미 판정 반복을 후보 생성의 반복 안정성으로 해석하지 않는다.

| 단계 | 최대 호출 | 호출당 입력 상한 | 호출당 출력 상한 | 비용 상한 |
|---|---:|---:|---:|---:|
| 새 GPT 후보 생성 | 36 | 12,000 | 1,500 | $0.2592 |
| Pair/Context/Rubric 각2회 | 648 | 12,000 | 2,000 | $5.1840 |
| 합계 | **684** | 총 **8,208,000** | 총 **1,350,000** | **$5.4432** |

입력 상한은 전체 요청 JSON·스키마의 UTF-8 바이트 수에 프레이밍 여유1024를 더한 보수적 토큰 상한이며 실제 토큰 사용량이 아니다. 초과 요청은 자르거나 재시도하지 않고 보류한다. 실제36개 생성 요청의 최대 입력 상한은8,578이고 초과 요청은0개다. 생성된 후보 수가 적거나 보류되면 의미 판정 호출도 줄어든다.

[공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-4.1-mini)를 다시 확인한 단가는 입력100만 토큰당$0.40, 출력$1.60이다. 캐시 할인은 예산에서 가정하지 않았다. 세금은 포함하지 않은 API 사용량 비용 상한이고 실제 청구액 확인과 구분한다. 문서는 모델을 Deprecated로 표시하지만, 기존 GitHub Secret으로 **2026-11-01 17:35:53 UTC(한국시간11-02 02:35:53)** GET 접근 확인은HTTP200이었다. [접근 확인 실행](https://github.com/sokldjs554/ko-search-clinic/actions/runs/41179770206/attempts/2), job124924702806. 이GET은 생성 호출·잔액/할당량 검증이 아니다.

## 동결·격리·원시 증거

부모 계획 hash는 `c7dbbe5f59c9106ab8386f5cb05be5bec673f4bd4d03c413a3fc71c538028563`이다. 공개 질의·문서의 동결 입력, 새 생성 요청, 코드 해시, 통계 조건, 최대 비용을 묶는다. 후보 생성 후 원시 응답을 다시 파싱해 후보를 복원하고, 같은 부모 hash를 갖는 자식 판정 계획을 도출한다. 별도 승인은 검증한 코드 커밋의 자식 커밋에서 `ops/v5-generated-approved.json` 한 파일만 바꾸는 방식으로 기록하며 자동 재실행을 막는다. 승인 파일은 아직 만들지 않았다.

후보 생성과 의미 판정 프로세스는 기존 평가 정답 모듈·선언한 비공개 정답 경로·과거 원시 결과 경로를 읽지 못한다. 준비 프로세스는 기존 공개 기록에서 질의ID·질의문만 추출하고 후보와 결과는 새 모델에 넘기지 않는다. 검색 순위를 봉인한 뒤 다른 프로세스에서만 기존 개발 정답으로 채점한다. 이 절차는 새 요청의 정답 직접 접근을 막는 장치이며 기존 개발 자료의 노출 자체를 없애거나 OS 수준 격리를 증명하지 않는다.

요청 전 비용을 예약하고 원시 응답·usage·HTTP오류·처리 시간을 배타적 파일 생성으로 보존한다. 알 수 없는 과금/전송 오류에서는 다음 호출을 멈춘다. 생성 오류, 전부 기각, 일부 기각, 의도적인 빈 후보를 구별하며 원래 응답 내 후보 위치를 보존한다. `study-summary.json`의 생성 집계·비용과 별도 비교 보고서의 판정 집계·비용을 함께 사용한다. 키와 원시 응답은 공개 로그로 출력하지 않고 Actions 산출물은 암호문·집계 영수증만 업로드한다.

## 비교와 해석 범위

Rubric을 주조건으로 고정한다. No Repair와 RulesPlus 각각에 대한 평균nDCG@10 차이의 보정97.5%구간 하한이+0.01 이상이고 정상 질의의 어느 지표도 어느 주조건 반복에서도 악화되지 않는지 확인한다. 질의 내 반복 평균 후 기존 개발 개념군bootstrap2,000회와 Matched Random100회를 사용한다. 정상/실패 분석, Recall@10/P@5, 후보 생성 Oracle·유용 후보 미선택, 적용/보류율, 비용과 처리 시간을 분리 보고한다.

confidence0.8은 보정된 개선 확률이나 최적 임계값이 아니다. 기존 grounding/zero-hit 후속 방법을 다시 분석하더라도 고정된 부차적 개발 분석으로 분리한다. 새 후보에 대한 추가 사람 의미 판정은 없으므로 새 인간 검증 정확도를 주장하지 않는다. 수치 조건을 만족해도 개발셋 결과이며 **독립 최종 성능 우위는 미검증**으로 남긴다. v4 성공 실행의 노출 감사 미완료 상태도 바꾸지 않는다.

## 무료 검증과 재현

생성 오류·승인 변경·키 반사 제거·원시 결과 위변조·빈 후보·유효 형제 후보 보존·과거90회 제한·부모별 자식 계획 분리를 테스트했다. 별도 코드 리뷰가 찾은 ‘전부 기각을 자발적 보류로 집계’ 문제는 실패 테스트로 재현한 뒤 수정했다. 모의 재실행에서 발견한 서로 다른 부모 계획 사이의 빈 자식 계획 충돌도 회귀 테스트 후 수정했다. Windows 인코딩 누락 검사도 반영했다. 수정 후 전체 로컬 pytest는704통과·2선택 의존성 제외·실패0(114.29초), 핵심 검사는69통과다. 로컬36질의 모의 생성→판정→순위 봉인→별도 채점을 완료했고 새 provider 호출은0회다. 상세 실행 상태는 [집계 검증 기록](verification/generated-comparison-preflight-20261102.json)을 따른다.

읽기 전용 리뷰의 경미한 후속 항목은 생성 요청 전부가 초과하는 경우와 판정 요청 전부가 초과하는 경우에 대한 전용 통합 테스트다. 빈 후보 경로·요청 크기 제한·누락 판정 보류는 기존 검사로 다루지만 이 두 조합의 별도 테스트는 추가하지 않았다. 이 한계를 실제 테스트 완료로 표시하지 않는다.

```bash
python scripts/run_v5_generated.py prepare --out work/new-comparison/prepared
python scripts/run_v5_generated.py mock --study work/new-comparison/prepared/study.json --out work/new-comparison/mock --protected-root <private-label-directory>
python scripts/compare_v5_conditions.py assemble --bundle work/new-comparison/mock/candidates.json --protocol work/new-comparison/mock/analysis.json --transport-dir work/new-comparison/mock/judges --protected-root <private-label-directory> --out work/new-comparison/mock/assembly.json
python scripts/compare_v5_conditions.py score --assembly work/new-comparison/mock/assembly.json --labels <private-development-labels.json> --out work/new-comparison/mock/report.json
```

모의 응답은 의도적으로 빈 후보를 반환한다. 그 검색 점수는 실제 GPT 성능이 아니다. 유효 후보가 있는 연결은 가짜HTTP응답을 사용하는 별도 무료 테스트로 검증한다. 원시 실패·부분 기록을 삭제해 같은 계획을 재실행하지 않는다. 새 실험 승인과 `main` 병합 승인은 별개다.

실행 코드 `098dc05`의 [CI41333235453](https://github.com/sokldjs554/ko-search-clinic/actions/runs/41333235453)는 Ubuntu704통과·2제외(89.60초), Windows704통과·2제외(146.28초), 검색 품질 gate 성공이다. [원격 무료 준비41333230489](https://github.com/sokldjs554/ko-search-clinic/actions/runs/41333230489)도 성공했으며 로컬과 같은 부모 계획 hash를 생성했다. 새 승인 부재로 유료 단계는 건너뛰었다. 이 검증 기록만 추가하는 후속 문서 커밋은 실행 코드를 바꾸지 않는다.
