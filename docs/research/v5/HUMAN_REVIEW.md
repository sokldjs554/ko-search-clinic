# 새 KLUE 후보 자료의 사람 검수

현재 실제 검수자는 배정되지 않았고 완료된 검수는0건이다. 아래는 실행할 절차와 빈 양식이다. 준비 담당 에이전트를 독립 사람 판정자로 세지 않는다. 원문 및 qrels는 공개 PR·웹페이지에 붙이지 않는다.

1. 한국어 독해가 가능한 사람 두 명을 배정하고 별도 reviewer ID와 시간 기록을 남긴다. 개발자가 후보/selector/결과를 보고 검수했다면 독립성 조건 미충족을 기록한다. 최종 판정자는 어떤 arm 결과·추천 patch·source 정답·서로의 grade도 보지 않는다. 각 reviewer에게 v2 `inputs.json`과 자신의 pair CSV만 제공하고 `private/`는 제공하지 않는다. 공개 ID는 query/document마다 별도 namespace로 hash되어 있으며 concept/source 연결 필드는 제거됐다. 이전 v1 입력은 사용하지 않는다. source span·source GUID·질의→원문 passage mapping은 독립 최초 판정이 완료된 뒤 조정 담당자에게만 제공한다.
2. `reviewer-a-pairs.csv`, `reviewer-b-pairs.csv`는 서로 다른 고정 순서의 **동일한 전체 split 내부40,800 pair**다. CSV의 query_id/doc_id를 inputs에서 찾아 읽는다. 빈 grade를 0으로 해석하지 않는다. corpus 규모 때문에 검수량이 크며, 현재 이것을 사람이 완료했다는 주장은 없다. 검수 자원이 부족하면 완전 qrels라는 주장을 포기하고 별도 pooled-evaluation protocol을 사전에 동결해야 한다.
3. grade 기준은 `0=질문 해결에 도움이 되지 않음`, `1=유용한 부분 근거지만 질문의 전체 답을 주지 않음`, `2=질문의 답을 직접 뒷받침함`으로 사용한다. 원문 인용/문장 위치를 evidence에 기재한다. 모호하면 grade를 비워두고 ambiguity에 이유를 쓴다. source의 answerability1/0을 자동 복사하지 않는다. 특히 source unanswerable은 해당 문서에서 답을 못 찾았다는 뜻이며 corpus 전체에 답이 없다는 뜻이 아니다.
4. query-review에는 질문의 의미, 여러 해석 가능성, source context 없이도 이해 가능한지, 개인정보/시점 의존성, 비슷한 개념 및 과거 노출과의 의미상 겹침을 기록한다. article title은 concept ID의 자동 정답이 아니다. 표현만 다른 같은 개념을 묶고 split을 넘는 개념·문서·질의 중복을 조사한다. 현재 source group IDs를 그대로 인증하면 안 된다.
5. 두 사람의 최초 제출본을 write-once로 보존하고 hash·시간을 기록한다. pair coverage, 중복, grade 범위, reviewer 불일치 여부를 검사한다. 단순 일치율과 ordinal weighted kappa를 계산하되 클래스 불균형·모호함 빈도도 함께 보고한다. 빈 판정이나 누락pair가 남으면 complete=false다.
6. 불일치는 제3의 한국어 검수자가 arm 결과를 보지 않고 증거와 이유를 검토하여 조정한다. 두 원판정과 최종판정·조정 이유·adjudicator ID를 모두 남긴다. 질문 자체가 결정 불가능하면 eligibility=`excluded_ambiguous`로 두고 사전 기준에 따라 제외한다. 점수가 나빠서 제외하거나 같은 수만큼 유리한 질의를 보충하지 않는다.
7. 이전36/pilot/120의 전체 exposure 목록 및 문서·개념 검사를 완료한다. 특히 암호화120 목록이 없는 지금은 complete exposure attestation에 서명할 수 없다. 사람이 source corpus에 익숙했거나 결과를 이미 보았다면 그 노출을 기록하고 blind라는 표현을 쓰지 않는다.
8. 검수 완료 후 원본200개/보류/제외/최종포함 counts와 이유, query→concept mapping, 전 pair의 최종 qrels, source/input/selection/review/adjudication hash를 별도 산출물로 동결한다. 판정이 모두0인 질의는 해당 **전체 split corpus**가 실제 판정되었을 때만 all-nonrelevant로 인정한다. final corpus/query/sample 변경 시 새 protocol version으로 다시 동결한다.

모든 gate를 만족하기 전 `candidate_review_pending`, `final_evaluation_ready=false`를 유지한다. 준비물의 attestation-template는 readiness checklist다. 비교 runner가 요구하는 별도 sealed attestation에는 `input_hash`, `protocol_hash`와 `eligibility_verified`, `human_review_complete`, `exposure_audit_complete`, `independent_concepts_verified`, `frozen_before_final_outcomes`, `candidate_generation_verified`의 실제 증거가 있어야 한다. 단순 boolean 변경으로 증거를 대체하지 않는다.

공개할 수 있는 빈 양식은 [human-review-pair-template.csv](human-review-pair-template.csv), [human-review-adjudication-template.csv](human-review-adjudication-template.csv)다. 실제 상세 pair CSV는 ignored `work/v5-independent-klue-v2/review/`에만 생성되어 있다.

## 개발15후보의 별도 의미 검수

검색 관련성 검수와 별개로 `work/v5-followup/semantic-human-review/`에 후보15개와 서로 다른 순서의 reviewer-a/b CSV를 준비했다. 완료 판정은0건이다. 검수자는 blinded-inputs의 질의·원문 근거·수정 후보만 보고 LLM 판정, confidence, qrels, 검색 점수는 보지 않는다. [공개 빈 양식](human-review-semantic-template.csv)은 상세 후보를 포함하지 않는다.

`meaning_preserved`는 후보의 모든 수정 요소가 질문 대상과 의미 범위를 보존하면 true, 하나라도 훼손하면 false, 판단 불가능하면 빈칸이다. 원문에 두 표현이 있다는 사실만으로 true를 부여하지 않는다. `error_type`에는 synonym_vs_hierarchy, category_vs_value, target_changed, scope_changed, unsupported_evidence, other 중 해당 유형을 기록하고, 원문 인용과 설명을 evidence에 남긴다. 여러 오류는 세미콜론으로 구분한다. 검색 효용이나 모델 confidence로 의미 정답을 정하지 않는다.

두 검수자는 서로의 판정을 보지 않고 제출하며, 제3자가 불일치를 근거와 함께 조정한다. 원본 두 CSV와 조정본 모두 hash와 시간을 보존한다. 확정 판정만 comparison CLI의 human-semantics 형식 `{query_id: {candidate_index문자열: true/false/null}}`으로 전달한다. 모호한 null은 미검수/판단 불가로 남기며 최종 평가의 완전 검수 gate를 통과시키지 않는다. 이 개발15후보 검수는 새 독립 평가 자료의 검수를 대신하지 않는다.
