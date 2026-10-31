# 새 한국어 평가 후보 자료: KLUE MRC

2026-10-31에 공식 KLUE 저장소의 **새 자료를 실제 내려받아** 로컬 준비를 실행했다. 기존 상품36질의나 MIRACL/v3/v4의120질의를 재포장한 자료가 아니다. 다만 과거120의 전체 노출 목록이 없으므로 이 문장의 의미는 **새 출처에서 새로 추출했다는 것**이며, 완전 비중복·blind final 인증은 아니다. 현재 상태는 `candidate_review_pending`, `final_evaluation_ready=false`다.

## 출처와 적합성

- 출처: [KLUE MRC v1.1 dev](https://github.com/KLUE-benchmark/KLUE/blob/3efd98708a40ff49251fddde35453f8fbb11f536/klue_benchmark/klue-mrc-v1.1/klue-mrc-v1.1_dev.json).
- 고정 revision: `3efd98708a40ff49251fddde35453f8fbb11f536`.
- 실제 다운로드: 18,712,914 bytes; SHA256 `b31bb073e47cdeb19f2f1bae03d916ecabf945140334c75842d6994f700d4f47`.
- 라이선스: 같은 revision의 [README License](https://github.com/KLUE-benchmark/KLUE/blob/3efd98708a40ff49251fddde35453f8fbb11f536/README.md#license)에 CC BY-SA 4.0 명시. README SHA256 `1f87facecc35feabf8ad25ecd2eda75bab8ea3ad074569b5239b4d57197ea059`. 원문 재배포 시 KLUE 및 원 출처 표기와 동일조건변경허락 의무를 확인한다. 이번 변경에는 원문을 넣지 않는다.
- 인용: Park et al. (2021), *KLUE: Korean Language Understanding Evaluation*, [arXiv:2105.09680](https://arxiv.org/abs/2105.09680).

한국어 원문 질의·문서와 사람의 QA 정답 구간/무응답 주석이 있어 기계번역 질의보다 적합하다. 그러나 이것은 **retrieval relevance qrels가 아니라 QA answerability proxy**다. 답이 있는 출처 passage를 임시 positive로, 무응답 출처 passage를 임시 negative로 기록한다. 답이 없는 passage도 부분적으로 관련될 수 있으므로 retrieval grade는 사람이 다시 판정해야 한다. 다른 passage는 정답0으로 채우지 않는다. 장문 뉴스/백과 질문의 자료이며, 상품 단문 검색이나 형태분석 실패 분포를 대표하지 않는다. 공개 벤치마크여서 모델의 사전학습 노출도 배제할 수 없다.

## 결과와 선택 규칙

| 항목 | 실제 준비량 |
|---|---:|
| 원본 전체 QA | 5,841 (answerable 4,008 / unanswerable 1,833) |
| 새로 선택한 질의 | 200 |
| source answerability proxy positive / negative | 160 / 40 |
| corpus | 300문서 (질의 원문200 + 별도 distractor100) |
| calibration | 40질의 / 60문서 |
| candidate_final | 160질의 / 240문서 |
| split 내부 전체 query-document pair | 40,800 |
| source에도 판정이 없는 pair | 40,600 |
| 실제 human review / provider call / retrieval scoring | 0 / 0 / 0 |

고정 seed `ko-search-clinic-v5-independent-20261031`와 SHA256을 사용한다. source ID 순위로 answerable160개를 먼저, 이미 사용한 그룹을 제외하고 unanswerable40개를 선택한다. title 또는 normalized context가 겹치는 문서는 연결 그룹으로 묶고 그룹당 질의 한 개만 선택한다. title이 없는 원본은 해당 article의 context 집합으로 그룹을 만든다. source question type나 검색 결과를 보고 교체하지 않는다. 별도 hash 순위로40/160을 분리하고 미사용 그룹의 문서100개를 distractor로 추가한다. distractor는 **무관하다고 검증된 negative가 아니라 잠재적인 negative 후보**다.

정답 구간은 원문 offset과 모든 문자열이 정확히 맞는지 검사했다. ID/정규화 질의 중복, 문서/기사그룹의 split 간 중복, distractor 그룹의 split 간 중복 검사를 통과했다. 기사그룹은 semantic concept의 대용물일 뿐이다. 동의 개념·유사 질문형·준중복 문서는 독립 사람 검수가 남아 있다.

원본 선택·split·corpus·proxy labels는 검색 점수를 전혀 계산하기 전에 파일로 고정했다. 모델 후보군이나 baseline 결과로 성공 사례를 선별하지 않았다. 현재 healthy/failure strata를 부여하지 않았으며, 특히 source unanswerable40개를 corpus 전체 all-nonrelevant 질의로 간주해서는 안 된다.

## 과거 노출 점검 범위

현재 상품36질의와 catalog72문서, 저장된 MIRACL ko-dev **전체213질의**를 정규화하여 비교했다. 선택200질의와 전체300문서에 대해 확인 가능한 exact normalized query/document/title overlap은 모두0이었다. MIRACL213질의 검사는 pilot12보다 넓지만 다음 공백을 해소하지 않는다.

- 과거 encrypted120의 전체 질의·문서·개념 목록을 확보하지 못했다.
- MIRACL pilot의 선택 passage 원문 corpus는 현재 로컬에 없다. topic 문자열은 검사했으나 passage 원문 비교는 불완전하다.
- title 일치 검사는 의미상 개념 동일성이나 부분/준중복 문서 검사를 대체하지 않는다.

노출 목록이 뒤늦게 확보되면 원문/정규화/준중복/개념 감사를 추가한다. 충돌은 제거·교체로 숨기지 않고 원래 표본의 제외 사유와 변경 이력을 남긴다. 새 protocol/version을 동결하기 전까지 final을 실행하지 않는다.

## 로컬 파일과 재현

상세 원문·질의·proxy labels·review pair 목록은 전부 git ignored `work/` 아래 있다. 공개 문서에는 집계, 출처, hash만 기록한다.

- `work/v5-independent-source/`: 고정 JSON과 라이선스 README cache.
- `work/v5-independent-klue-v2/inputs.json`: 질의/문서/split과 서로 독립적으로 hash한 opaque ID만 포함한다. source GUID·concept/article 그룹·질의→원문 passage 연결 정보는 없다.
- `work/v5-independent-klue-v2/private/identity-split-audit.json`: public ID↔source ID, 질의→원문 passage, 기사/개념 그룹 및 split 검사 정보. 판정자용 입력과 분리한다.
- `work/v5-independent-klue-v2/selection.json`: 고정 seed·선택 정책·원본 counts.
- `work/v5-independent-klue-v2/private/source-proxy-labels.json`: source answer span과 **sparse proxy_qrels**. final `labels.json`이 아니다.
- `work/v5-independent-klue-v2/private/known-exposure.json`: 실제 점검한 과거 identity/text 목록.
- `work/v5-independent-klue-v2/audit.json`, `summary.json`, `manifest.json`: 차단 사유·집계·파일별 SHA256.
- `work/v5-independent-klue-v2/review/`: 사람 둘의 독립 순서 all-pair sheet, query review, 미완료 attestation template.

첫 준비물 `work/v5-independent-klue/`는 보존했다. 그 자료의 공개 입력에는 기사 그룹 ID가 있어 질의와 원문 passage의 연결을 추론할 수 있었다. 이를 검수자에게 제공하지 않는다. 현재 표본·split은 그대로 유지하면서 관계 메타데이터를 private로 옮긴 **v2**를 새 디렉터리에 만들었고, 기본 CLI 출력도 v2를 사용한다. source 답 구간은 private source annotations에만 남으며 독립 최초 판정 이후 조정 담당자만 확인한다. 이 수정으로 최종 blind 인증이 이루어진 것은 아니다.

주요 v2 hash:

| 파일 | SHA256 |
|---|---|
| inputs.json | `bd746a88a743e9d0188f4bd874d73d21ad1fa4448e5bbca9a01c2e3a4bba6134` |
| selection.json | `4d75be295666cdda75108dcef16e73f212aad401103471dd2f9fc30f2620103b` |
| private/source-proxy-labels.json | `5cadf6c22e26eb8d9b697841cb175b88666a577d8333b5806a8153ee85df5f3b` |
| private/known-exposure.json | `375a83f9f84198847c278a669b2e72c2c66113696090ec5187e0348ddd97e80d` |

최초 cache 확보는 무료 공개 URL 다운로드만 수행한다. provider API/LLM/키를 사용하지 않는다.

```bash
python scripts/prepare_v5_independent.py --download
# 동일 cache로 새 디렉터리에 오프라인 재현; 기존 output 덮어쓰기 금지
python scripts/prepare_v5_independent.py --out work/v5-independent-klue-v2-reproduced
python -m pytest tests/test_v5_dataset.py
```

`--extra-exposure local.json`은 `{query_id, query, document_texts, concept_ids}` 목록을 추가한다. 목록을 공급했다는 이유만으로 completeness를 true로 바꾸지 않는다. CLI는 상세 자료가 공개 경로에 놓이지 않도록 cache/output을 저장소 `work/`로 제한한다.

[사람 검수 지침](HUMAN_REVIEW.md)을 따라 두 명의 독립 검수와 제3자 불일치 조정, 전체 노출·개념 검증을 마친 뒤 별도 final labels와 protocol/input hash에 묶인 attestation을 만든다. 준비 template만 채웠다고 runner의 final gate가 열리지 않는다. 현재 자료로 최종 성능/개선률을 주장할 수 없다.

검증: label-isolation 회귀 테스트를 먼저 실패시킨 뒤 수정했으며 focused dataset tests 6개가 통과했다. v2 산출물12개와 manifest를 별도 디렉터리에서 byte-for-byte 재현했다. Manifest SHA256: `12d67332ff6af6ef6e1bcfffbe8dc2e5a05ae98bc2aee61784e2dd35650c9afe`.
