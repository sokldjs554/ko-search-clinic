# Elasticsearch 실연결 검증

렌더러(`patch/es_render.py`)는 "로컬 패치가 nori 설정과 1:1로 대응한다"고
주장한다. 이 문서는 그 주장을 **실제 Elasticsearch에 물려 확인하는 절차**다.

## 무엇을 확인하려는 것인가

확인하려는 것은 "ES에서도 됩니다"가 **아니다.** Kiwi와 nori는 서로 다른
형태소 분석기이므로 토큰화는 어차피 완전히 같을 수 없고, 같기를 기대하는
것 자체가 틀렸다. 알고 싶은 것은 하나다:

> 로컬 회귀 게이트를 통과해 채택된 패치가, nori 설정으로 옮겨진 뒤에도
> **같은 방향의 효과**를 내는가? 아니라면 어느 질의에서, 왜 갈리는가?

그래서 산출물은 합격 도장이 아니라 **질의별 차이표와 토큰화 차이**다.
갈리는 질의가 나오면 그것은 실패가 아니라 발견이며, 그대로 기록한다.

## 어떻게 비교가 성립하는가

`ElasticsearchEngine`은 로컬 `SearchEngine`과 **같은 `search(query, k)`
시그니처**를 갖는다. 덕분에 채점 코드(`evaluate_query`/`evaluate_all`)를
한 줄도 바꾸지 않고 양쪽에 그대로 쓴다 — 자를 공유해야 차이가 백엔드의
차이로만 남는다.

두 백엔드에서 다른 것은 오직 분석과 색인이 어디서 일어나느냐다:

| | 로컬 | Elasticsearch |
|---|---|---|
| 토큰화 | Kiwi 형태소 분석 | `nori_tokenizer` |
| 품사 필터 | 내용어 화이트리스트 | `nori_part_of_speech` (stoptags) |
| 사용자 사전 | `add_user_word` | `user_dictionary_rules` |
| 복합어 분해 | 파이썬 후처리 확장 | `decompound_mode: mixed` |
| 동의어 | 파이썬 정규화 | `synonym_graph` |
| 랭킹 | 자체 BM25 (k1=1.2, b=0.75) | Lucene BM25 (동일 기본값) |

**필드 구성이 특히 중요하다.** 로컬 엔진은 `name + " " + description`을
통짜로 색인한다. ES에서 필드를 나눠 검색하면 BM25의 필드 길이 정규화가
달라져 점수를 비교할 수 없으므로, 매핑에서 `copy_to`로 두 필드를 합친
`text` 필드를 만들고 검증은 그 필드로 한다.

## 실행 (Windows / Docker Desktop 기준)

Docker Desktop이 WSL2 백엔드로 실행 중이어야 한다. PowerShell에서:

```powershell
# 1) ES + analysis-nori 컨테이너 빌드 및 기동 (최초 1회는 플러그인 설치로 수 분)
docker compose -f docker/docker-compose.yml up -d --build

# 2) 준비될 때까지 대기 — healthy가 뜨면 된다
docker compose -f docker/docker-compose.yml ps

# 3) 검증 실행
clinic es-verify --output docs/ES_VERIFICATION_REPORT.md

# 4) 정리
docker compose -f docker/docker-compose.yml down -v
```

Claude가 채택한 설정으로 검증하려면 (API 키 필요, 호출 16회):

```powershell
clinic es-verify --engine claude --output docs/ES_VERIFICATION_REPORT.md
```

인덱스를 남겨 직접 들여다보려면 `--keep`을 붙이고, 그 뒤에:

```powershell
curl "http://localhost:9200/ko-search-clinic/_analyze?pretty" `
  -H "Content-Type: application/json" `
  -d '{\"analyzer\":\"clinic_korean\",\"text\":\"아답터\"}'
```

### 자주 걸리는 것

| 증상 | 원인과 조치 |
|---|---|
| `connection refused` | 컨테이너가 아직 안 떴다. `docker compose ps`로 healthy 확인 후 재시도 |
| `analysis-nori 플러그인이 없습니다` | 기본 ES 이미지로 띄웠다. `--build`를 빼먹지 않았는지 확인 |
| 컨테이너가 바로 죽음 | Docker Desktop 메모리 부족. Settings → Resources에서 4GB 이상으로 |
| 한글이 깨져 보임 | PowerShell 출력 인코딩 문제. `chcp 65001` 후 재실행 |

## CI는 Docker 없이 돈다

`tests/test_es_verify.py`는 가짜 클라이언트로 **요청의 형태**(bulk NDJSON,
`_meta` 제거, refresh 지정)와 **대조 리포트의 판정**(갈림 표시, 토큰 차이
기록)을 고정한다. ES가 있어야만 검증되는 코드는 CI에서 영영 안 돌게 되고,
안 도는 코드는 반드시 썩는다.
