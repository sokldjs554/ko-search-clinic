# 보존된 v1 detector 오류 분석

원천: `artifacts/research/validation/runs/selective_rule-20261012T045403-46bbb6d9.json`.
실제 결과 생성 source SHA: `7a43aae61460ebb2727ec00ed19fd677c2ba1149`, source hash: `3010cfc44138220613874b388c551e9dfd49ac1fc0ac43da2f08e9fb33fedf86`.
프로토콜과 질의·임계값을 바꾸지 않고 원본 JSON에서 생성했다.

| 오류 | 질의 | 반환 수 | top1 | top2 | 상대 margin | coverage | score | reason | nDCG/recall/P5 | 진단 시도 | 제출 | 채택 | 최종 행동 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| false_positive | 프라이팬 | 2 | 4.377900 | 3.983500 | 0.090089 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 케이크 | 2 | 5.071400 | 4.605900 | 0.091789 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 1 | False | typed_patch |
| false_positive | 주스 | 2 | 4.489000 | 4.272200 | 0.048296 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 어댑터 | 2 | 4.605900 | 4.377900 | 0.049502 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 물티슈 | 2 | 4.729100 | 4.489000 | 0.050771 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 샤인머스캣 | 2 | 4.996200 | 4.605900 | 0.078119 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 트레이닝복 | 2 | 4.859000 | 4.729100 | 0.026734 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 카펫 | 2 | 4.489000 | 4.489000 | 0.000000 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_positive | 리모컨 | 2 | 4.996200 | 4.605900 | 0.078119 | 1.000000 | 0.6 | low_score_margin | 1.0/1.0/1.0 | True | 0 | False | abstain |
| false_negative | 텀블러 | 1 | 5.168600 | null | null | 1.000000 | 0.1 | 규칙 미발동 | 0.6131/0.5/1.0 | False | 0 | False | no_op |
| false_negative | 백팩 | 4 | 5.594600 | 3.123800 | 0.441640 | 1.000000 | 0.1 | 규칙 미발동 | 0.0/0.0/0.0 | False | 0 | False | no_op |

## 오탐 원인

건강 오탐은 프라이팬·케이크·주스·어댑터·물티슈·샤인머스캣·트레이닝복·카펫·리모컨이다.
모두 coverage=1이며 두 관련 문서가 비슷한 BM25 점수를 가진다. 프라이팬의
상위 두 문서는 둘 다 grade 2 정답이고 nDCG/recall/P5가 모두 정상이다.
그러나 상대 margin이 고정 하한보다 작아 실패로 판정한다. 카펫의 동점도
같은 경우다. margin은 순위 구분의 약함이며 문서의 무관함을 직접 측정하지 않는다.
이는 평가 후 원인 분석이다. qrels를 detector 입력으로 넣거나 이 질의를 제외하지 않는다.

오탐의 건강 개입은 후보를 찾기 위한 진단 시도다. 그 중 실제 gate 제출은
케이크에서만 발생하고 기각됐다. 다른 오탐은 진단 후 근거 있는 후보가 없어
abstain했으며 패치를 제출·채택한 것으로 세지 않는다.

## 미탐 원인

텀블러는 한국어 문서 한 개를 정상 검색하지만 영어 tumbler 문서를 놓쳐
recall이 부족하다. top2가 없어 margin=null이고 coverage=1이라 모든 실패
규칙이 미발동한다. 결과 수와 현재 매칭 coverage만으로 누락 문서를 알 수 없다.

백팩은 분석기에서 분해한 짧은 토큰이 에코백·물티슈·주스의 무관한 문서에
겹쳐 coverage=1, 큰 margin을 만든다. 그러나 정답 배낭 문서는 반환하지 않는다.
lexical coverage는 분석된 토큰 일치일 뿐 의미 일치를 보장하지 않는다.

건강 9건 오탐과 실패 2건 미탐은 모두 기존 결과의 부정적 증거로 보존한다.
후속 detector 검증은 별도의 독립 데이터에서 계획하며 현재 threshold를 바꾸지 않는다.
