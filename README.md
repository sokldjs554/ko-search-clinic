# ko-search-clinic

[![CI — main](https://github.com/sokldjs554/ko-search-clinic/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sokldjs554/ko-search-clinic/actions/workflows/ci.yml?query=branch%3Amain)

한국어 검색 실패를 형태소·검색 결과로 진단하고, 사용자 사전·동의어·복합어 수정안을 검증하는 Python 프로젝트입니다. 120질의 연구에서는 규칙·GPT 후보의 실제 검색 효과를 비교했고, 최신 서비스 작업에서는 운영 문서를 검색해 GPT 설명과 원문 인용을 검증하는 RAG 점검 화면을 추가했습니다.

**상태 확인: 2026-10-28.** 기본 브랜치와 최신 작업 브랜치의 구현 범위가 다릅니다.

| 구분 | 구현·검증 범위 | 현재 상태 |
|---|---|---|
| `main` | Kiwi + BM25 검색, 규칙·임베딩·Claude 진단, 수정안 회귀 게이트, REST/MCP, 지식 검색 평가 | 이 README의 기본 실행 대상 |
| [최신 RAG 서비스 — PR #2](https://github.com/sokldjs554/ko-search-clinic/pull/2) | 점검 화면, GPT 설명·원문 인용 검증, 수정 후보 검사, 비용·오류 제어, 실제 API 응답 24건 | Draft · 미병합, 확인한 커밋 `493935f` |
| [선택적 검색 복구 — PR #1](https://github.com/sokldjs554/ko-search-clinic/pull/1) | 선택적 개입 정책, 비용·재현성 기록, 개발용 평가 | Draft · 미병합, 확인한 커밋 `3238d58` |
| 120질의 연구 — [v3 실행 기록](https://github.com/sokldjs554/ko-search-clinic/actions/runs/38842054422) · [v4 실행 기록](https://github.com/sokldjs554/ko-search-clinic/actions/runs/39044121771) | No Repair·RulesPlus·GPT 비교, 저장 후보 재평가 | 최종 보고 완료 · 별도 연구 실행, `main` 기본 CLI에 통합되지 않음 |

`main`과 RAG 서비스의 기본 자료는 직접 구성한 **상품 카탈로그 72건 · 평가셋 36질의(건강 20 + 실패 16)**입니다. 별도의 120질의 연구(v3·v4) 결과는 아래에 정리했습니다. 개발용 검색 평가, 120질의 연구, RAG 응답 검증은 데이터와 목적이 다른 실험이며 합산하지 않습니다. 실제 채용 공고나 고객 검색 로그를 사용한 성과가 아닙니다.

## 120질의 검색 수정 비교

정상 60질의·실패 60질의에서 **No Repair(수정 없음), RulesPlus(규칙), GPT**를 비교했습니다. 아래 수치는 보존된 v3 최종 보고와 v4 최종 연구 요약을 대조한 기록입니다. 공개 Actions 링크는 생성 실행 완료의 근거이며, 원시 응답·결과는 암호화 보존돼 있습니다. 이번 문서 갱신에서 원시 결과를 새로 복호화·재계산하지는 않았습니다.

실패 개선은 기준 검색 대비 **nDCG@10 증가 ≥ 0.05**, 정상 회귀는 **nDCG@10·Recall@10·Precision@5 중 하나의 감소 > 0.02**로 집계합니다. 후보 적용 정책이 바뀐 후속 실험이므로 각 버전의 점수는 해당 실행 조건 안에서 비교합니다. v3→v4의 절대 점수 차이를 모델의 성능 변화로 해석하지 않습니다.

### v4 — 최종 비교 결과

| 비교군 | 전체 120질의 평균 nDCG@10 | 실패 60질의 중 개선 | 정상 60질의 중 회귀 |
|---|---:|---:|---:|
| No Repair | 0.6993592 | 0 | 0 |
| RulesPlus | 0.6993592 | 0 | 0 |
| GPT | 0.6993592 | 1 | 0 |

고정 모델 `gpt-4.1-mini-2025-04-14`로 **73건을 생성**하고 후보를 확정·보존한 뒤 별도로 채점했습니다. GPT 후보 목록은 **63/73건이 입력·출력 규약 검증을 통과**, 10건이 실패했습니다. 실제 적용은 2건으로, 실패 질의 하나는 **+0.2262**, 다른 하나는 **−0.2262**여서 전체 평균 이득이 없었습니다. 정상 질의에 적용된 수정안은 0건이므로 정상 회귀 0건만으로 안전성을 입증하지 않습니다.

최종 보고에는 저장 후보를 다시 적용·채점한 결과가 원래 결과와 정확히 일치했고 재생성은 없었다고 기록돼 있습니다. 범주와 그 안의 특정 값을 동의어로 묶는 의미 오류가 남았으며, **후보의 형식 준수와 실제 검색 효용을 별도로 검증해야 한다**는 결론입니다.

- [v4 생성 실행](https://github.com/sokldjs554/ko-search-clinic/actions/runs/39044121771) · [봉인 완료 manifest](https://github.com/sokldjs554/ko-search-clinic/blob/5d9549e9af776349dc5b0d06dfc2f5adce228517/transfer/39044121771/checkpoint-sealed-221.json)
- 초기 파일럿 원본을 복구하지 못해 평가 자료와의 중복을 완전히 확인하지 못했습니다. 인위적인 60/60 표본의 결과를 실제 질의 전체나 독립 맹검 평가의 성능으로 일반화하지 않습니다.

### v3 — 원본 공식 정답 기준

| 비교군 | 전체 120질의 평균 nDCG@10 | 실패 60질의 중 개선 | 정상 60질의 중 회귀 |
|---|---:|---:|---:|
| No Repair | 0.7143467 | 0 | 0 |
| RulesPlus | 0.7192483 | 2 | 0 |
| GPT | 0.7150100 | 7 | 6 |

실제 GPT 생성은 **68회**였으며 모델은 v4와 같은 고정 버전입니다. GPT−RulesPlus의 전체 평균 차이는 **−0.0042383**입니다. 실패 질의 개선 수와 정상 질의 회귀를 함께 보면 안전하고 효과적인 GPT 우위는 확인되지 않았습니다. 정답 없는 관측·근거로 후보를 생성·선택·적용하고 최종 설정·순위를 봉인한 뒤 공식 정답으로 채점했습니다. [v3 생성 실행](https://github.com/sokldjs554/ko-search-clinic/actions/runs/38842054422)

**사후 사용자 정답 보정:** 같은 저장 순위로 117질의를 계산하고, 모호한 판정이 남은 3질의는 `NA`로 유지했습니다. 따라서 전체 120질의의 단일 보정 평균은 **미확정**이며, 117질의 평균으로 대체하지 않습니다. 생성·수정안 적용·검색을 새로 실행한 결과가 아닙니다.

과거 별도 사후 게이트 분석의 GPT 평균 **0.7259**는 최종 정답을 사용해 채택 여부를 정한 진단값입니다. 위의 정답 없는 v3 주평가 **0.7150100**과 구분하며, 운영 성능으로 제시하지 않습니다.

v3는 공개 MIRACL 한국어 `ko-dev`의 **2,455문단 judged-pool**과 인위적인 60/60 표본을 사용했습니다. 모델 사전학습 노출 가능성, 정답 불일치와 사후 판정, 단일 모델·실행의 한계가 있으며 전체 MIRACL 코퍼스나 실제 트래픽의 결과를 나타내지 않습니다.

## 최신 RAG 서비스 살펴보기

최신 화면은 `feat/alba-rag-service-20261027` 브랜치에 있습니다. `main`을 설치하면 아래 화면용 모듈은 포함되지 않습니다.

Python 3.11 또는 3.12에서 별도 폴더로 실행합니다. 아래 활성화 명령은 macOS/Linux 기준이며, Windows PowerShell에서는 `.\.venv\Scripts\Activate.ps1`을 사용합니다.

```bash
git clone --branch feat/alba-rag-service-20261027 --single-branch https://github.com/sokldjs554/ko-search-clinic.git ko-search-clinic-rag
cd ko-search-clinic-rag
git checkout 493935f6b7ddd9201e67125a4897e8e76ffd67f8
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[api]'
python -m searchclinic.api.explanation_api
```

[http://127.0.0.1:8000/demo/](http://127.0.0.1:8000/demo/)에서 **저장 결과 열람**을 선택하면 API 키 없이 24건의 실제 모델 응답을 재검증한 기록을 확인할 수 있습니다. 저장 결과를 읽는 동작에는 새 API 호출이 없습니다.

구현한 흐름은 다음과 같습니다.

1. 질의 형태소와 상품 검색 결과, BM25로 찾은 운영 지식 3개를 구성합니다.
2. GPT 응답에서 설명·실패 유형·원문 인용·수정 후보를 분리합니다.
3. 문서 ID, 실제 본문 인용, Pydantic 스키마와 수정 규칙을 검사합니다.
4. 사용자가 검사를 요청한 후보를 기존 36개 질의로 검증하고, 채택된 후보만 별도 세션에 적용합니다.

**적용 범위:** 새 질의의 설명 생성은 가능하지만 수정안 검사·적용은 정답표가 있는 기존 36개 평가 질의로 제한됩니다. 새 생성 기록은 최근 64건, 세션은 기본 최대 32개를 메모리에 보관하며, 기본 실행에서 프로세스 재시작 시 사라집니다. 필요한 진단은 JSON으로 내려받아 보존합니다.

실제 생성은 별도 활성화와 서버 측 API 키·운영 토큰이 필요합니다. 비용 예약, 자동 재시도 없음, 취소·오류 처리와 접근 범위는 [운영 문서](https://github.com/sokldjs554/ko-search-clinic/blob/493935f6b7ddd9201e67125a4897e8e76ffd67f8/docs/alba-operation.md)에 정리돼 있습니다. 이 브랜치에서는 Kiwi 0.24.1, 모델 0.24.0, `cong-global`을 고정합니다.

### 2026-10-27 검증 결과

작성한 사례 12개에 검색 문서를 제공하거나 제거한 두 조건을 적용해 실제 OpenAI API를 **24회** 호출했습니다. 입력 19,797토큰, 출력 3,152토큰이며 추정 비용은 **$0.02903175**입니다.

| 저장 응답 24건의 재검증 | 결과 |
|---|---:|
| 형식·인용 조건 통과, 수정 후보 있음 | 6 |
| 판단 보류 | 12 |
| 형식·인용·상태 문제로 차단 | 6 |
| 후보 6건의 회귀 검사 | 채택 4 / 기각 2 |

최초 검증에서 차단된 12건을 분석한 뒤 줄바꿈·강조 표시의 원문 대응을 보완하고 **같은 응답을 추가 API 호출 없이 재검사**했습니다. 사후 검증이며, 독립 평가에서 모델 정확도가 향상됐다는 뜻이 아닙니다. 후보 6건은 각각 새 세션에서 검사했으므로 누적 검색 개선이나 고객 효과를 나타내지 않습니다.

확인한 커밋 `493935f`의 CI는 Ubuntu·Windows 각각 **318 passed, 2 skipped**, 검색 품질 게이트 성공입니다.

- [최신 README와 화면](https://github.com/sokldjs554/ko-search-clinic/blob/493935f6b7ddd9201e67125a4897e8e76ffd67f8/README.md)
- [사전 계획·원시 응답·전후 판정·환경·한계](https://github.com/sokldjs554/ko-search-clinic/blob/493935f6b7ddd9201e67125a4897e8e76ffd67f8/docs/verification/alba-20261027/README.md)
- [실제 API 실행](https://github.com/sokldjs554/ko-search-clinic/actions/runs/40463356460) · [해당 커밋 CI](https://github.com/sokldjs554/ko-search-clinic/actions/runs/40466724243)

## main 빠른 시작

`main`의 CLI와 REST/MCP를 실행하는 방법입니다. CI는 Python 3.11을 사용합니다.

2026-10-28 새 설치 환경(Python 3.12, Kiwi 0.24.1, 모델 0.24.0)에서는 `포도`가 `포`로 분석돼 기존 분석기 테스트가 실패하는 것을 확인했습니다. 아래 설치는 이전 CI의 분석기 조합인 **Kiwi 0.23.2 + 모델 0.23.0**을 명시합니다. `main`의 의존성 정의와 CI 자체에는 아직 이 버전 고정이 없습니다.

```bash
git clone --branch main --single-branch https://github.com/sokldjs554/ko-search-clinic.git
cd ko-search-clinic
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[api,mcp,dev]' 'kiwipiepy==0.23.2' 'kiwipiepy_model==0.23.0'

# 형태소와 검색 실패 확인
clinic analyze "아답터"
clinic search "후라이팬"
clinic evaluate

# 과잉 동의어 기각과 최소 수정안 채택 시연
clinic demo-trap

# API 키 없이 규칙 기반 복구
clinic heal --engine scripted
clinic heal --engine rules+
clinic heal --engine vector+

# 생성 모델 호출 없이 지식 검색만 비교
clinic rag-eval --compare

# 기존 기준선과 비교
clinic baseline
python -m pytest -q
```

`vector`·`vector+`는 커밋된 벡터 캐시로 실행할 수 있습니다. 캐시를 새로 만들 때만 `python -m pip install -e '.[vector]'`와 `clinic build-vectors`가 필요합니다.

분석기 버전과 모델 종류는 형태소·지표에 영향을 줍니다. 버전을 고정하지 않은 설치나 다른 모델의 결과를 아래 과거 측정치와 동일하게 간주하지 않습니다. `clinic baseline`으로 현재 환경을 먼저 대조합니다.

### 선택 기능

| 기능 | 설치·실행 |
|---|---|
| REST API | 위 설치 후 `clinic-api --host 127.0.0.1 --port 8000` — `/health`, `/docs` |
| MCP 서버 | 위 설치 후 `clinic-mcp` |
| Claude 진단 | `python -m pip install -e '.[llm]'`, `ANTHROPIC_API_KEY` 설정 후 `clinic heal --engine claude` |
| Claude + 지식 검색 | 위 LLM 설정 후 `clinic heal --engine claude --prompt minimal --rag` |
| 데이터 레이크·로그 집계 | `python -m pip install -e '.[scale]'`, `clinic build-lake`, `clinic mine-logs --engine duckdb` |
| Spark 로그 집계 | 앞 행의 데이터 레이크 생성 후 `python -m pip install -e '.[spark]'` 및 Java 환경, `clinic mine-logs --engine spark` |
| Elasticsearch nori 대조 | Docker 환경에서 [실연결 검증 절차](docs/ES_VERIFICATION.md) 실행 |

Claude 진단은 실제 API 호출을 수행합니다. 일반 CLI 평가, 규칙 엔진, 저장 캐시 기반 비교에는 API 키가 필요하지 않습니다.

## main·RAG 서비스의 수정안 검증

`후라이팬`처럼 표기가 다르거나 `백팩`이 잘못 분해되면, 검색 결과만 정렬해서는 해결되지 않는 실패가 생깁니다. 이 프로젝트는 사용자 사전·동의어·복합어 분해 확장을 타입이 있는 수정안으로 받습니다.

- **진단:** 검색 결과, 원문 검색, 형태소 분석, 후보 토큰을 확인합니다.
- **검사:** 수정안을 별도 엔진에 적용하고 평가셋 전체를 다시 실행합니다.
- **채택:** 표적의 개선과 비표적 질의의 nDCG·recall·precision@5 및 전체 평균 조건을 확인합니다.
- **기각:** 적용하지 않고 어떤 질의·지표가 악화됐는지 반환합니다.
- **기록:** 채택된 설정과 표적·근거·전후 지표를 원장에 남깁니다.

회귀 허용치는 `ε=0.02`이며, 게이트는 REST/MCP가 공유하는 서비스 아래에서 실행됩니다. `clinic baseline`은 같은 평가셋을 커밋된 기준선과 비교해 코드·코퍼스 변경에 따른 회귀를 검사합니다. `clinic baseline --write`는 기준선을 바꾸므로 일반 확인 명령과 구분합니다.

## 기존 개발용 벤치마크 기록

아래는 `main`에 저장된 리포트의 결과입니다. 같은 사람이 설계한 문서와 질의를 사용했으며, 독립 평가나 실제 서비스 성능으로 일반화하지 않습니다.

| 엔진 | 복구한 실패 질의 | 실패셋 평균 nDCG@10 | 기록 |
|---|---:|---:|---|
| `scripted` — 자모 규칙 | 10/16 | 0.695 | [리포트](docs/CLINIC_REPORT.md) · [원장](docs/LEDGER.json) |
| `rules+` — 2단계 수정·재시도 | 11/16 | 0.757 | [리포트](docs/CLINIC_REPORT_RULES_PLUS.md) · [원장](docs/LEDGER_RULES_PLUS.json) |
| `vector` — 자모·임베딩 | 11/16 | 0.737 | [리포트](docs/CLINIC_REPORT_VECTOR.md) · [원장](docs/LEDGER_VECTOR.json) |
| `vector+` — 규칙·임베딩·재시도 | 12/16 | 0.799 | [리포트](docs/CLINIC_REPORT_VECTOR_PLUS.md) · [원장](docs/LEDGER_VECTOR_PLUS.json) |

과거 문서에 기록된 **Claude 16/16·nDCG 0.980**은 별도로 해석해야 합니다. 현재 `main`에는 해당 실행의 원시 요청·응답과 Claude 전용 리포트·원장이 없어 실행 모델·프롬프트·사용량까지 재검증할 수 없습니다. 따라서 현재 검증된 대표 성과로 사용하지 않습니다. [후속 근거 감사](https://github.com/sokldjs554/ko-search-clinic/blob/564a664ae533dba65935211f4534cdaf7eda4643/docs/research/CURRENT_STATE_AUDIT.md)

선택적 개입의 후속 개발용 결과는 [Phase 0–1 결과 문서](https://github.com/sokldjs554/ko-search-clinic/blob/564a664ae533dba65935211f4534cdaf7eda4643/docs/research/RESULTS_PHASE01_V2.md)와 [PR #1](https://github.com/sokldjs554/ko-search-clinic/pull/1)에 있습니다. 이 결과도 RAG 저장 응답 재검증과 별도이며, 각 문서의 평가셋·실행 상태·원본 기록을 기준으로 읽습니다.

임베딩 비교의 결론 역시 사용한 모델·토큰 후보·코퍼스 범위에 한정합니다. 두 모델의 비슷한 결과만으로 모든 임베딩 모델이나 모델 선택 일반에 대한 결론을 내리지 않습니다. [벡터 분석 기록](docs/VECTOR_PROBE.md)

## 테스트와 실행 범위

`.[api,mcp,dev]` 설치 후 기본 CI 조건에서 수집되는 **테스트 277개**를 기준으로 문서 수치를 관리합니다. PostgreSQL·데이터 레이크의 선택 의존성 및 `slow` 표시에 따라 수집·건너뜀 수는 달라질 수 있습니다. 최신 RAG 브랜치의 CI 결과는 위의 별도 커밋 링크에 표시했습니다.

기본 CI는 Ubuntu·Windows에서 `pytest -q`를 실행하고, 별도 작업에서 `clinic baseline`을 검사합니다. README의 테스트 수와 카탈로그·평가셋 규모도 기존 계약 테스트가 확인합니다.

2026-10-28 문서 갱신 시 위 재현 설치(Python 3.12.14, Kiwi 0.23.2, 모델 0.23.0)로 **277 passed, 2 skipped**를 확인했고, `clinic baseline`은 평균 nDCG **0.5839**로 통과했습니다. 이 로컬 검증과 버전이 고정되지 않은 원격 CI 상태는 구분하며, 현재 CI 상태는 상단 배지에서 확인합니다.

## 운영 한계

- **평가 범위:** 직접 작성한 카탈로그·질의, 120질의 연구, RAG 저장 응답 실험을 구분합니다. 각 실험의 한계는 해당 결과에 명시했으며, 고객 지표와 독립 데이터에서의 일반화 성능을 이 결과로 주장하지 않습니다.
- **main·RAG 서비스의 수정안 적용 대상:** 채점할 정답표가 있는 평가 질의가 필요합니다. 임의의 새 질의를 진단했다고 바로 회귀 검사·적용할 수 있는 구성은 아닙니다.
- **저장소:** 기본 REST/MCP 세션은 메모리입니다. PostgreSQL 저장소 구현은 있지만 `ClinicService(store=...)`에 명시적으로 연결해야 하며, `DATABASE_URL` 설정만으로 기본 실행기가 영속 저장을 활성화하지 않습니다.
- **접근 제어:** `main` REST/MCP에는 인증이 없습니다. RAG 브랜치의 운영 토큰도 생성·적용 경로의 제어이며 기존 API 전체의 공개 서비스 인증을 제공하지 않습니다.
- **검사 비용:** 수정안마다 색인과 평가를 다시 구성합니다. 대규모 서비스의 처리량·지연을 보장하는 구현은 아닙니다.
- **설명과 효과:** 인용이 원문에 존재하는지, 진단이 맞는지, 검색이 개선되는지는 서로 다른 검증 대상입니다. 형식·인용 통과를 진단 정확도로 계산하지 않습니다.

## 코드와 문서

| 위치 | 역할 |
|---|---|
| `src/searchclinic/analysis/`, `index/` | Kiwi 분석·설정, 자모·벡터 후보, BM25 색인 |
| `src/searchclinic/doctor/`, `patch/`, `evaluation/` | 진단 루프, 수정안 IR, 회귀 게이트, 지표·원장 |
| `src/searchclinic/service.py`, `api/` | 세션 격리, REST/MCP |
| `src/searchclinic/rag/` | 지식베이스, 청킹, BM25·dense·hybrid 검색 평가 |
| `src/searchclinic/es/`, `scale/`, `store/` | Elasticsearch 대조, 규모·로그 실험, 선택적 PostgreSQL 저장소 |
| `tests/`, `.github/workflows/` | 기능·문서 계약 검사와 검색 품질 CI |

- [기본 아키텍처](docs/ARCHITECTURE.md) · [평가 방법](docs/EVALUATION.md)
- [규칙·재시도 비교 기록](docs/FAIRNESS.md) · [지식 검색 평가 기록](docs/RAG_RETRIEVAL.md)
- [Elasticsearch 검증 절차](docs/ES_VERIFICATION.md) · [기준선](docs/BASELINE.json)
- [RAG 서비스 운영 문서](https://github.com/sokldjs554/ko-search-clinic/blob/493935f6b7ddd9201e67125a4897e8e76ffd67f8/docs/alba-operation.md) · [RAG 검증 기록](https://github.com/sokldjs554/ko-search-clinic/blob/493935f6b7ddd9201e67125a4897e8e76ffd67f8/docs/verification/alba-20261027/README.md)

기본 아키텍처·평가 문서에는 과거 실행 기록도 포함됩니다. 현재 구현 범위와 결과의 해석은 이 README의 브랜치 구분과 각 실행의 원본 기록을 함께 확인합니다.
