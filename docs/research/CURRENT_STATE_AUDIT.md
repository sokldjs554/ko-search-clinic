# 현재 상태 감사 — Phase 0

시작 main SHA: `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`.
작업 브랜치: `feat/selective-retrieval-repair-v2`. 최신 main을 fetch하고 확인했다.
README·v1 JSON은 이 감사 시점에 변경하지 않았다.

## 실행 근거

실측 단일 출처는 `artifacts/research/audit/v1-kiwi-0.23.2.json`과
`v1-kiwi-0.24.0.json`이다. 아래 표는 JSON에서 생성했다. 원본 결과를 갱신하지 않았다.

- 카탈로그 72건; healthy 20건; failing 16건.
- 계열: compound_locked, cross_script, garbage_split, spelling_variant, synonym_gap. evalset의 expected kinds는 synonym, compound_expansion, user_word+synonym과 일치한다.

| 실제 재실행 | 치유 건수 | 실패 nDCG 전 | 실패 nDCG 후 | 건강 회귀 | 원장 완전 일치 |
|---|---|---|---|---|---|
| scripted | 10 | 0.0696 | 0.6946 | 0 | False |
| rules+ | 11 | 0.0696 | 0.7571 | 0 | False |
| vector | 11 | 0.0696 | 0.7367 | 0 | False |
| vector+ | 12 | 0.0696 | 0.7992 | 0 | False |

치유 건수와 README의 반올림 표는 오프라인 네 엔진에서 재현됐다. 원장
완전 일치는 실패했다. 누적 mean의 일부 끝자리 등 차이는 audit JSON의
실제 ledger와 docs/LEDGER*.json을 대조할 수 있다. 덮어쓰지 않는다.

## Claude provenance와 재시도

README/EVALUATION의 Claude 16/16, 실패 nDCG 0.980, healthy 회귀 0은
문서 주장이다. 현재 커밋된 LEDGER.json은 scripted 10개 처방이며 Claude의
원시 요청/응답, timestamp, usage, 모델 응답 ID를 가진 JSON은 없다.
`doctor/llm.py`의 DEFAULT_MODEL은 `claude-opus-5`이고 prompt variants는
full/minimal이나 저장된 Claude 실행의 실제 model/prompt hash는 미확인이다.
이번 환경에는 LLM 키가 없어 재실행하지 않았다. 이 설계에서도 이를 신규
측정치로 인용하지 않는다.

MAX_SUBMITS=3, MAX_TURNS=16이다. `test_loop.py`는 가짜 모델의
rejected_then_corrected, max_submits, target 변경, schema 오류 전달을
시험한다. 이는 실제 Claude 재처방 능력의 측정이 아니다. rules+의 아답터
재시도는 audit cases/ledger attempts로 확인할 수 있다.

## 검색·캐시·청킹

| mode | recall@5 | precision@5 | MRR | KB cache coverage |
|---|---|---|---|---|
| bm25 | 0.3104 | 0.3625 | 0.375 | 0.0592 |
| dense | 0.3554 | 0.4 | 0.6427 | 0.0592 |
| hybrid | 0.3338 | 0.3875 | 0.2917 | 0.0592 |

캐시 모델 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 캐시 token 470, catalog vocabulary coverage 1.0.

기존 RAG_RETRIEVAL.md의 표는 현재 재실행과 일치하지 않는다. 캐시가 상품
어휘 중심이고 지식 KB coverage가 낮아 dense 결과를 embedding 일반 능력으로
해석할 수 없다. 신규 숫자는 audit JSON에만 보존하고 기존 문서를 덮어쓰지 않는다.
청킹 비교는 audit JSON 및 별도 실제 CLI 출력으로 확인했다. 기존 문서의
청킹 부정적 결과는 역사적 결과이고 이번 실행에서는 개선 증거가 없다.

## 게이트·Elasticsearch·CI

run_gate는 표적 이득 0.05와 비표적 세 지표 ε=0.02를 검사한다. 전체 평균
설명은 하락 없음이나 구현은 ε=0.02까지 허용한다. v2 어댑터는 기존 허용치를
보존한다. 기존 harness의 healthy_regressions는 precision5를 검사하지 않으므로
신규 runner의 최종 검사에서는 세 지표를 모두 확인한다.

ES_SETTINGS.json은 렌더링 산출물이다. ES_VERIFICATION.md는 과거 실연결
서술이며 원시 서비스 응답 JSON은 없다. mock client 테스트나 렌더링 테스트를
현재 Elasticsearch 실측으로 취급하지 않는다. 이번 단계 ES 실연결은 미확인이다.

CI는 ubuntu/windows의 pytest와 ubuntu의 clinic baseline을 실행한다. slow
marker는 기본 제외되고 scale extras는 설치하지 않으므로 optional scale
테스트는 skip될 수 있다. corpus_contract의 문서 숫자 대조는 실험 재실행이
아니다. main의 실제 push CI는 실패였다.
[실제 CI run](https://github.com/sokldjs554/ko-search-clinic/actions/runs/32585720148):
276 passed, 2 skipped, README test count 308 vs 실제 selected 277 때문에
1 failed. 증거는 main-ci.json에 보존했다.

현재 unconstrained Kiwi 0.24.0에서는 포도가 포로 분해돼 기존 analyzer 테스트가
실패했다. Kiwi 0.23.2는 main CI가 실제 사용한 버전이다. 연구 재현 constraints로
이 버전을 고정하고 품질 기준선을 다시 검사한다. README의 테스트 개수는
선택 의존성에 따라 달라지므로 실험 이후 고정 개수 주장을 제거할 예정이다.

초기 기본 샌드박스 pytest는 REST TestClient 지점에서 중단했다. 네트워크
권한으로 REST 테스트 전체가 통과했으므로 loopback 실행 환경 제한으로
구분한다. 본체 테스트를 건너뛰는 조치 대신 같은 권한에서 전체 실행한다.

Kiwi 0.23.2 전체 재실행: 295 passed, 1 skipped, 2 deselected, 1 failed
(기존 README 테스트 개수 계약). 기능 회귀는 발견되지 않았으나 이 시점 전체
테스트는 통과 상태가 아니다. 로그를 audit 폴더에 보존했다.
