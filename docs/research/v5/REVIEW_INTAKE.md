# 독립 검수 전달·제출본 검증 — 2026-10-31

**2026-11-01 갱신:** a·b·c가 서로 다른 실제 담당자로 배정됐고, a·b의 제출30행을 수령했다. 사용자 설명에 따른 정규화 후 공통 확정5건의 일치율60%, κ−0.25이며 이후 c의 조정12건을 수령해 개발 판정 TRUE12/FALSE3을 정리했다. 날짜 없는 시각은 추정하지 않고 내용 수령과 엄격한 메타데이터 검증을 구별한다. [현재 연구 결론](RESEARCH_CONCLUSION_20261101.md). 아래는 2026-10-31 전달 준비 당시의 재현 기록이다. 이 단계는 기존90회 LLM 실험의 결과를 바꾸지 않는다. 추가 모델 호출0회, 독립 평가 미완료, 성능 우위 미입증 상태를 유지한다.

## 현재 전달 준비 상태

기존 개발15후보의 의미 검수 제출은 완료됐다. 새 KLUE 검색 관련성은 별도 과제이며 현재189질의·289문서로 전달물을 갱신했다. 원래 순서를 유지한 채 노출 보류11개 개념군만 제외했다. 사용자가 다른 검수자2인 확보 가능을 확인해 d·e의 개발·보정용 Excel을 준비했다. 실제 새 판정은0건이며 총괄 담당자가 각자에게 자기 파일만 전달한다.

| 검수 | 1인당 항목 | 최초 판정자 | 실제 완료 | 로컬 전달물 |
|---|---:|---:|---:|---|
| 기존 개발 후보 의미 | 15 | a·b, 조정 c | 제출 완료 | 기존 제출본 보존; 재작성 없음 |
| 새 KLUE 개발·보정 관련성 | 2,016쌍 | 새 검수자 d·e | 0 | 비공개 Excel2개; 우선 Q01의56행부터 제출 가능 |
| 새 KLUE 최종 후보 관련성 | 35,649쌍 | 후속 단계 | 0 | `work/v5-continuation-20261101/candidate_final-source/`; 보정용 전달물과 분리 |

각 ZIP은 자기 `inputs.json`, 불변 `template.csv`, 편집용 `submission.csv`, 해시 묶음 `packet.json`, 한국어 `INSTRUCTIONS.txt`만 포함한다. 다른 판정자 파일·LLM 응답·source QA 답안·정답표는 포함하지 않는다. 관리자가 실제 별칭과 독립성 확인을 별도로 기록한 뒤 각자에게 **자기 ZIP만 비공개 전달**한다. 에이전트는 사람에게 메시지를 보내지 않았다.

이전 semantic 입력에는 검색 관측값과 생성자의 진단·이유가 남아 있었다. 새 전달물은 질의, 원문, 수정 내용만 추출하고 검색 건수/점수/토큰·생성자 진단과 이유를 제거했다. 이전 파일은 수정하지 않고 보존했다. 새 관련성 전달물은 원문과 질의·분할만 제공하며 source QA 연결은 제공하지 않는다.

KLUE 검수량은 두 사람 합계75,330쌍(calibration4,032·candidate_final71,298)으로 크다. 자원이 부족하면 검수한 일부만 완전 qrels라고 부르지 않는다. 표본/pooled 평가로 바꾸려면 결과를 보기 전에 별도 프로토콜을 동결해야 한다. 이번 작업에서는 평가 모집단을 줄이거나 쉬운 질의를 고르지 않았다.

## 판정 입력

상세 기준과 독립성·모호성·개념 검수는 [HUMAN_REVIEW.md](HUMAN_REVIEW.md)를 따른다.

- 의미: `meaning_preserved=true/false`; `false`이면 오류 유형 필수. Excel의 `TRUE/FALSE`도 허용한다. `1/0`으로 의미 판정을 대체하지 않는다.
- 관련성: `grade=0/1/2`. 0은 실제 비관련 판정이며 빈칸과 다르다.
- 확정 판정에는 원문 근거와 이유, 실제 담당자 별칭, 실제 판정 UTC 시각이 필요하다.
- 판단 불가면 값을 비우고 `ambiguity`에 이유를 쓴다. 아직 읽지 않은 항목은 빈칸으로 남긴다.
- 두 판정자는 서로의 판정이나 LLM confidence·검색 효용을 보지 않는다. 별칭을 다르게 적는 것만으로 독립성은 입증되지 않는다.
- `submission.csv`만 편집한다. 제출 이후에는 원본을 수정하지 않고 수정 제출도 새 버전/새 출력 폴더에 보존한다.

## 무료 CLI 실행

상세 경로는 모두 저장소의 ignored `work/` 아래여야 한다. 기존 출력 경로를 다시 사용하면 중단한다. 아래는 새로운 작업 디렉터리 예시다.

```bash
# 재현 예시: 기존 의미 제출은 완료됐으므로 semantic 명령은 재검수 요청이 아니다.
# 관련성 준비는 현재 보류 반영 source를 사용한다. private/ 원본 정답 경로는 접근 차단한다.
python scripts/review_v5.py prepare --kind semantic \
  --source work/v5-followup/semantic-human-review --out work/my-review/semantic
python scripts/review_v5.py prepare --kind relevance \
  --source work/v5-continuation-20261101/relevance-source --out work/my-review/relevance

# 실제 제출본이 생긴 뒤 실행한다. reviewer ID는 예시가 아닌 실제 배정 별칭으로 바꾼다.
python scripts/review_v5.py validate \
  --packet work/my-review/semantic/reviewer-a \
  --submission work/my-review/semantic/reviewer-a/submission.csv \
  --reviewer-id REVIEWER_A --out work/my-review/intake-a-v1
python scripts/review_v5.py validate \
  --packet work/my-review/semantic/reviewer-b \
  --submission work/my-review/semantic/reviewer-b/submission.csv \
  --reviewer-id REVIEWER_B --out work/my-review/intake-b-v1
python scripts/review_v5.py reconcile \
  --review-a work/my-review/intake-a-v1/receipt.json \
  --review-b work/my-review/intake-b-v1/receipt.json \
  --out work/my-review/comparison-v1
```

`validate`는 입력·템플릿·전체 판정 대상 해시, 중복/외부ID/분할/값/근거/UTC 시각을 검사한다. 빈칸·모호함·누락을 따로 집계하며, 제출 원본 바이트와 검수 packet 사본을 receipt 옆에 보존한다. `reconcile`은 이 원본 파일에서 판정을 다시 산출해 receipt와 비교한다. JSON의 counts나 해시 문자열만 믿지 않는다.

판정자 둘이 모두 확정 판단한 항목에 대해서만 일치율과 kappa를 계산한다. 의미는 이진 unweighted, 관련성은 ordinal quadratic weighted kappa를 쓴다. 분모와 제외된 항목 수를 확인해야 한다. 둘 다 같은 상수 등급만 매겨 기대 불일치가0이면 kappa는 `null`이다. 검수0건일 때도 kappa를0이나1로 꾸미지 않는다.

불일치와 판단 불가 항목은 `receipt.json`의 queue와 `adjudication-template.csv`에 남는다. 최초 판정 누락은 원 판정자가 채워야 하며 조정자가 대신 채울 수 없다. 조정자는 두 최초 판정자와 다른 별칭을 사용해야 한다. 별칭의 대소문자·앞뒤 공백 차이로 이 제한을 우회할 수 없다.

```bash
# 제3자가 실제 작성한 조정본이 있을 때만 실행한다.
python scripts/review_v5.py reconcile \
  --review-a work/my-review/intake-a-v1/receipt.json \
  --review-b work/my-review/intake-b-v1/receipt.json \
  --adjudications work/my-review/comparison-v1/adjudication-template.csv \
  --out work/my-review/adjudicated-v1
```

조정 양식은 `query_id`, `candidate_index`(관련성은 `doc_id`), `final_value`, `adjudicator_id`, `decision_reason`, `adjudicated_at_utc`이다. 이전의 일반 지침용 adjudication CSV와 헤더가 다르므로 **CLI가 생성한 양식**을 사용한다. 부분 조정은 나머지를 보류한다. 중복 행·일치 판정 덮어쓰기·최초 누락 대리 판정은 거부한다. 조정 원본의 정확한 바이트, SHA256, 수집 UTC 시각도 보존한다.

모든 항목이 해결돼야 `private/labels.json`을 만든다. 의미 검수는 `{query_id: {candidate_index: boolean}}`, 관련성 검수는 `{query_id: {doc_id: grade}}`다. **관련성 qrels 파일만으로 최종 비교를 실행하지 않는다.** 질의 적격성, 정상/실패 구분, 개념군, 과거 노출, 실제 사람 독립성, 후보/프로토콜 동결은 별도 증거가 필요하며 이 도구는 최종 attestation을 발행하지 않는다. `final_evaluation_ready`는 항상 false다.

## 실제 실행한 검증과 남은 입력

2026-11-01 현재189/289 전달물을 기존 CLI로 준비하고 두 빈 제출본을 검증·대조했다. 각각37,665개 모두 미판정이고 정답 파일은 생성되지 않았다. 이는 전달물·빈칸 처리 검증이며 실제 사람 검수0건이다. 아래40,800쌍은 최초 준비 시점의 기록이다.

실제 전달물4개 ZIP의 파일 목록·바이트 해시·허용 필드를 검사했다. 빈 제출본을 실제 CLI로 수집하고 대조했으며 의미15/관련성40,800개 모두 미판정으로 남고 정답 파일이 생성되지 않음을 확인했다. [질의 내용 없는 준비도 기록](verification/review-readiness-20261031.json)을 공개한다. 합성 테스트 판정을 실제 검수로 세지 않았다.

현재 외부 입력은 **새 검색 관련성 과제를 위한** 사람 검수 자원과 실제 판정이다. 기존 a·b·c의 의미 검수 배정·제출과 구별한다. 사용자는 성공한 v4 실행의 복호화 ZIP이 없다고 확인했다. 해당 복원은 미완료로 남기고 같은 파일·키를 반복 요청하지 않는다. 첫 중단 v4 입력과 v3 목록은 이미 확보했다. 전체 노출·개념 독립성 미검증 상태를 유지하며 키 값이나 상세 정답을 공개 저장소에 붙이지 않는다.

검수 기능 커밋 `af7da2a`는 로컬 및 [Ubuntu·Windows CI](https://github.com/sokldjs554/ko-search-clinic/actions/runs/41205762770)에서 각각694통과/2skip, 검색 baseline 통과를 확인했다. 별도 AI 코드 리뷰의 무결성·원본 보존 지적을 회귀 테스트로 수정했다. AI 코드 리뷰는 실제 사람 검수가 아니다. 기존90회 실험의 분석 프로토콜 해시는 변하지 않았다.
