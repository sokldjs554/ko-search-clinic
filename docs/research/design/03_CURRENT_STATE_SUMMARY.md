# 현재 저장소 확인 요약

대상: `sokldjs554/ko-search-clinic`  
기준 커밋: `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`

## 코드에서 확인한 내용

- `src/searchclinic/corpus/evalset.py`
  - 건강 질의 20개
  - 실패 질의 16개
  - 총 36개
  - 실패 계열 5개
- `src/searchclinic/doctor/loop.py`
  - 최대 turn 16
  - 최대 처방 제출 3회
  - gate 기각 피드백을 tool result로 모델에 반환
  - 평가셋 밖 질의는 채점 근거가 없어 실행 차단
- `pyproject.toml`
  - Python 3.10+
  - 기본 의존성은 Kiwi와 Pydantic
  - LLM/vector/API/scale 의존성을 선택적으로 분리
  - 기본 pytest에서 slow marker 제외

## 문서·커밋에서 확인한 내용

- 현재 README는 프로젝트를 챗봇이 아니라 한국어 검색 품질 자가 치유 에이전트로 정의한다.
- 보관 결과는 Claude 16/16 치유, 건강 질의 20개 회귀 0건으로 서술한다.
- 공정성 실험에서 규칙 의사에 추가 action과 retry를 부여해 비교했다.
- RAG 검색 평가는 지식 검색과 생성 사용 능력을 분리하려는 구조를 갖는다.
- 청킹은 현재 코퍼스에서 recall을 낮춘 부정적 결과가 기록되어 있다.
- 규모 실험은 정확성보다 전체 재색인 비용이 선형으로 증가한다는 한계를 보고한다.

## 구현 전 다시 확인할 항목

- 저장소를 실제로 checkout한 환경에서 전체 테스트 수와 통과 여부
- README 숫자와 최신 원장 JSON의 정확한 일치
- 실제 Claude model ID와 원시 호출 결과의 provenance
- 벡터 캐시 coverage의 최신 값
- 실제 Elasticsearch 검증 로그와 설정 렌더링만 한 결과의 구분
- 문서 정리 커밋 이후 CI 상태
