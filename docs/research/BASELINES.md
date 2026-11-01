# 실제 기준선 실행

아래 값은 `artifacts/research/validation/runs/*.json`에서 생성했다.
기존 scripted/rules+/vector/vector+ 재실행은 CURRENT_STATE_AUDIT와 audit JSON에 별도 보존한다.
세 새 정책은 동일 rules+ 후보 공간·근거 검사·최대 제출 예산을 사용한다.

| 정책 | 실패 치유 | 최종 실패 nDCG | 건강 진단 개입 | 실제 gate 제출 | 검색 호출 |
|---|---|---|---|---|---|
| always_typed_patch | 11/16 | 0.7571 | 20 | 15 | 1224 |
| no_repair | 0/16 | 0.0696 | 0 | 0 | 108 |
| selective_rule | 11/16 | 0.7571 | 9 | 13 | 1067 |

always rewrite·Claude one-shot·selective LLM·oracle 비교는 이번 단계에서 실행하지 않았다.
no repair는 생성된 처방을 적용하지 않는 비교군이다. always typed patch는
모든 질의에서 후보를 탐색하지만 없는 처방을 만들지는 않는다. selective rule은
탐지 신호와 효용에 따라 진단을 생략하거나 근거 없는 경우 보류한다.
