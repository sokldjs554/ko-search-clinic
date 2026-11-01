# Phase 0–1 한계

- 기존 공개 fixture를 개발 데이터로만 실행했다. train/test 독립 데이터가
  없으며 held-out 신뢰구간이나 외부 일반화 결과는 없다.
- 규칙 detector의 score는 calibration된 probability가 아니다. false positive와
  탐지 실패를 실제 결과의 query record에서 확인할 수 있다.
- span 무결성과 형태 관계 검사는 의미를 보장하지 않는다. 다의어·오동의어의
  완전한 의미 타당성 gate, blind repair, 독립된 근거 검증은 Phase 2 대상이다.
- rewrite/retriever switch/rerank는 행동 스키마와 fail-closed 경로만 있고 실행은
  지원하지 않는다. 최소 실험은 typed patch를 기존 게이트로 검증한다.
- 실제 rules+의 기각·재제출은 LLM 자가 수정 능력의 증거가 아니다.
- 유료 모델을 호출하지 않아 토큰/API 비용은 실제 0이다. 모델 호출 절감이나
  LLM 효용 우위를 검증한 실험은 아니다.
- wall-clock은 cold/warm Kiwi cache와 실행 순서, 부하의 영향을 받는다.
  단일 실행 지연을 속도 우위로 주장하지 않는다. 실제 latency가 정책 효용의
  경계를 넘나들면 seed가 같아도 선택이 달라질 수 있다.
- 전체 회귀 게이트의 재색인 비용은 유지했다. 제출 예산은 전체 지연의
  절대 상한을 보장하지 않는다.
- bootstrap은 공개된 작은 질의들의 기술적 요약이다. 개념별 상관이 있어
  독립 test 일반화 또는 통계적 유의성 근거로 사용하지 않는다.
- 원래 Claude 실행의 model/prompt/usage 원시 provenance는 현재 저장소에서
  확인하지 못했다. 문서의 과거 결과와 현재 오프라인 재실행을 구분한다.
- 실제 Elasticsearch, Spark, PostgreSQL, Windows 환경의 신규 실행은 확인하지
  않았다. 렌더링/mock/로컬 테스트를 실서비스 실행으로 표시하지 않는다.
- archive/wheel만으로는 고정 Git 커밋 검증을 수행할 수 없다. 전체 history가
  있는 checkout이 현재 지원되는 연구 재현 경로다.

지원서에서 사용 가능한 주장은 **오프라인 controlled-v1에서 검색 실패 탐지,
비용 선택, 전체 회귀 검증과 원장 기록을 연결하고 실제 비교한 연구 단위를
구현했다**는 것이다. 구체적 숫자는 RESULTS.md 및 원본 JSON을 함께 제시한다.
외부 일반화 입증, 모든 기준선 우위, LLM의 안정적 재처방, 실제 서비스 효과,
한국어 RAG 신뢰성 문제 해결이라는 주장은 사용할 수 없다.
