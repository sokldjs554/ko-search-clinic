# 실제 실패 분석

원천: `artifacts/research/validation/runs/*.json`. 이 표는 JSON에서 생성했다.

| 정책 | 질의 | 실제 gate 제출 | 최종 채택 | 마지막 결과 |
|---|---|---|---|---|
| always_typed_patch | 케이크 | 1 | False | rejected |
| always_typed_patch | 가습기 | 1 | False | rejected |
| always_typed_patch | 김치 | 1 | False | rejected |
| always_typed_patch | 블루투스 스피커 | 0 | False | abstain |
| always_typed_patch | 텀블러 | 0 | False | abstain |
| always_typed_patch | 핸드폰 | 0 | False | abstain |
| always_typed_patch | 츄리닝 | 0 | False | abstain |
| always_typed_patch | 아답터 | 2 | True | accepted |
| always_typed_patch | 백팩 | 0 | False | abstain |
| no_repair | 후라이팬 | 0 | False | no_op |
| no_repair | 케잌 주문 | 0 | False | no_op |
| no_repair | 도너츠 | 0 | False | no_op |
| no_repair | 쥬스 | 0 | False | no_op |
| no_repair | 소세지 | 0 | False | no_op |
| no_repair | 카페트 | 0 | False | no_op |
| no_repair | 초콜렛 | 0 | False | no_op |
| no_repair | 리모콘 | 0 | False | no_op |
| no_repair | 블루투스 스피커 | 0 | False | no_op |
| no_repair | 텀블러 | 0 | False | no_op |
| no_repair | 핸드폰 | 0 | False | no_op |
| no_repair | 츄리닝 | 0 | False | no_op |
| no_repair | 티슈 | 0 | False | no_op |
| no_repair | 머스캣 | 0 | False | no_op |
| no_repair | 아답터 | 0 | False | no_op |
| no_repair | 백팩 | 0 | False | no_op |
| selective_rule | 케이크 | 1 | False | rejected |
| selective_rule | 블루투스 스피커 | 0 | False | abstain |
| selective_rule | 텀블러 | 0 | False | no_op |
| selective_rule | 핸드폰 | 0 | False | abstain |
| selective_rule | 츄리닝 | 0 | False | abstain |
| selective_rule | 아답터 | 2 | True | accepted |
| selective_rule | 백팩 | 0 | False | no_op |

## 건강 질의 오탐

프라이팬; 케이크; 주스; 어댑터; 물티슈; 샤인머스캣; 트레이닝복; 카펫; 리모컨

## 결과가 있지만 실패인 사례

블루투스 스피커; 텀블러; 백팩

동률 또는 작은 score margin은 건강 질의에서도 생긴다. 원문 coverage가
높아도 의미 오류나 누락 문서는 구분하지 못한다. 형식 관계를 찾지 못하는
후보는 보류하며 임베딩 유사도만으로 동의어를 자동 채택하지 않는다.

아답터의 기각·두 번째 처방 채택은 rules+의 실제 행동이다. 인위적으로
틀린 프롬프트나 LLM 응답을 넣어 만든 실험이 아니다. LLM 재처방 능력은
이 사례로 검증하지 않는다. 회차별 정확한 처방·회귀·피드백은 trace에 있다.
