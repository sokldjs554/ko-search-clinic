# 연구 논문 구성 초안

가제: Selective Retrieval Repair for Korean Search under Regression and Cost Constraints.

1. 문제: 전체 질의에 복구를 적용할 때의 불필요 개입과 정상 질의 회귀.
2. 시스템: retrieval observation → rule detector → cost-aware typed action
   → 전체 회귀 게이트 → 채택/기각 → 근거 원장.
3. 프로토콜: 사전 고정 가설, 공개 개발 데이터와 미수집 held-out의 구분,
   탐지/복구/비용 분모, label leakage 차단.
4. 실험: no repair/always typed patch/selective rule의 실제 query-level JSON,
   기존 scripted/rules+/vector 계열은 별도 v1 감사 재실행으로 제시.
5. 실패 분석: 건강 질의 오탐, 결과가 있지만 잘못된 실패, 기각 후 재처방,
   남은 의미 관계/표기 교차 실패.
6. 한계: 작은 공개 도메인, 독립 test 부재, uncalibrated rule score,
   latency 변동, 의미 검증 불완전, 실제 LLM 실험 부재.
7. 후속 연구: Phase 2 held-out/semantic/blind repair, 이후 Phase 3 LLM·
   answer propagation·cross-domain. 이번 작업에서는 실행하지 않는다.

현재 결과는 시스템과 측정 프로토콜의 재현 가능한 최소 연구 단위다.
논문 수준의 일반화·유의성 주장은 후속 독립 평가가 필요하다.
