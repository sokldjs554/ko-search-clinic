# 재현성 보완 마무리 — 로컬 검증

기존 phase01-v1 결과를 보존했다. phase01-v2는 실측/예상 비용 분리의 사후 변경이며 detector·threshold·질의를 변경하지 않았다.

| v2 정책 | 실패 복구 | 실패 nDCG | 건강 진단 | 건강 제출 | 건강 채택 | 검색 호출 |
|---|---|---|---|---|---|---|
| always_typed_patch | 11/16 | 0.7571 | 20 | 3 | 0 | 1224 |
| no_repair | 0/16 | 0.0696 | 0 | 0 | 0 | 108 |
| selective_rule | 11/16 | 0.7571 | 9 | 1 | 0 | 1067 |

이 표는 성능 향상의 증거가 아니다. 기존 보존된 v1과 관측된 선택·품질·호출 수는 같았지만, 통제 지연 probe에서 재현성 결함을 수정했다.

최종 로컬 전체 테스트: 373 passed, 2 skipped. 새 지연/버전 테스트 20개와 기존 연구 테스트를 포함한 연구 suite는 76 passed. skip은 pyspark와 PostgreSQL 환경 부재다. clinic baseline도 통과했다.

결과 생성 source SHA: `73a9fcc379d37729cbe1ec8df8bbcb340511d28f`

source hash: `b6ee792476f148a0e3eb4ac37002ad23d1c194f6123f8b2db793b05f22b73e85`

프로토콜 사후 고정 커밋: `bb267e2853d5e66e9907fdf025ce651547765bca`

새 프로토콜 hash: `1e62a3811ae0f07b7bcaec72a19c12afbcd55442bfa057a6bb26de6d147c6a11`

## 변경 파일과 이유

- actions.py: expected_cost와 기존 실측 cost 분리.
- costs.py: latency weight가 0일 때 null 항을 제외하되 null 자체 보존.
- policy.py: 새 expected-v2 경로, 기존 measured-v1 기본값 유지.
- runner.py: 버전별 고정 프로토콜, 비용별 원장과 source provenance.
- cli.py: 명시적 새 root와 버전 일치 검사.
- artifacts.py: no repair 포함 전체 비교군 provenance 대조와 사후 표현.
- test_research_latency_reproducibility.py: 경계·null·보류·버전 누수 실패 테스트.
- CI: skip 사유와 실제 SHA/hash를 출력하고 버전별 artifact 업로드.
- 새 docs/artifacts: 원격 근거, 비용 probe, 오탐/미탐, 결과·보존 검증, Phase 2 계획.

## 남은 한계

예상 미래 latency를 보정하지 않았으므로 시간 예산 최적화는 미검증이다. 현재는 그 항을 제외하여 관측 지연만으로 선택을 바꾸지 않는다. 모델 호출은 없어 토큰/API 절감 주장을 하지 않는다. 결과는 controlled-v1/dev이며 실제 LLM/독립 held-out 실험은 실행하지 않았다. 초기 원격 artifact ZIP의 로컬 read-back은 HTTP 403으로 미확인이다.
