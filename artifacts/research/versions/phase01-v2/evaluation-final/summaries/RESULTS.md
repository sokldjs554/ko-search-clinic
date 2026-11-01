# Phase 0–1 실제 실행 결과

데이터: controlled-v1/dev. held-out 미수집; 일반화 결과 없음.
규칙 score는 보정된 확률이 아니다. 단일 wall-clock 실행으로 속도 우위를 주장하지 않는다.

| 정책 | 치유/실패 | 실패 nDCG@10 | 건강 회귀 | 건강 개입 | 제출 | 검색 호출 | 재색인 | 외부 모델 호출 | 지연 ms |
|---|---|---|---|---|---|---|---|---|---|
| always_typed_patch | 11/16 | 0.7571 | 0 | 20 | 15 | 1224 | 16 | 0 | 11296.266 |
| no_repair | 0/16 | 0.0696 | 0 | 0 | 0 | 108 | 1 | 0 | 2257.679 |
| selective_rule | 11/16 | 0.7571 | 0 | 9 | 13 | 1067 | 14 | 0 | 656.542 |

phase01-v2는 실측 지연과 예상 행동 비용을 분리한 사후 변경이다.
예상 미래 latency는 null이며 그 미보정 항의 weight만 0이다. 실제 지연은 위 표에 보존한다.
이 결과는 기존 phase01-v1 또는 held-out 성능을 대체하지 않는다.

검색 호출은 초기 관측·전후 평가·전체 회귀 게이트를 모두 포함한다.
건강 개입은 진단 실행도 포함하며 실제 제출과 구분한다.

| 정책 | AUROC | AUPRC | Precision | Recall | F1 | Brier | ECE | 건강 FPR | 불필요 개입률 | 첫 제출 채택률 | 기각 후 회복률 | 평균 제출 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| always_typed_patch | 0.8953 | 0.9061 | 0.6087 | 0.8750 | 0.7179 | 0.1434 | 0.1764 | 0.4500 | 1.0000 | 0.7143 | 0.2500 | 0.4167 |
| no_repair | 0.8953 | 0.9061 | 0.6087 | 0.8750 | 0.7179 | 0.1434 | 0.1764 | 0.4500 | 0.0000 | null | null | 0.0000 |
| selective_rule | 0.8953 | 0.9061 | 0.6087 | 0.8750 | 0.7179 | 0.1434 | 0.1764 | 0.4500 | 0.4500 | 0.8333 | 0.5000 | 0.3611 |

| 정책 | input tokens | output tokens | API USD |
|---|---|---|---|
| always_typed_patch | 0 | 0 | 0.0 |
| no_repair | 0 | 0 | 0.0 |
| selective_rule | 0 | 0 | 0.0 |

## 사후 변경 버전의 별도 판정

```json
{
  "status": "executed_controlled_dev",
  "H1": "supported",
  "H2": "supported",
  "H3": "rejected",
  "paired_ndcg": {
    "mean_delta": 0.0,
    "ci95": [
      0.0,
      0.0
    ],
    "samples": 2000,
    "interpretation": "descriptive controlled-dev only"
  }
}
```

## 실행 provenance

- always_typed_patch: git `73a9fcc379d37729cbe1ec8df8bbcb340511d28f`, source hash `b6ee792476f148a0e3eb4ac37002ad23d1c194f6123f8b2db793b05f22b73e85`, dirty=False;
  protocol `1e62a3811ae0f07b7bcaec72a19c12afbcd55442bfa057a6bb26de6d147c6a11`, split `43f8dc393b9686d4cae2bee1d7f4cedcb432ecf5143141afa1b6f34a2f31212b`, seed=20261012;
  환경: {"python": "3.12.14", "kiwipiepy": "0.23.2", "kiwipiepy_model": "0.23.0", "pydantic": "2.14.1", "model": null}
- no_repair: git `73a9fcc379d37729cbe1ec8df8bbcb340511d28f`, source hash `b6ee792476f148a0e3eb4ac37002ad23d1c194f6123f8b2db793b05f22b73e85`, dirty=False;
  protocol `1e62a3811ae0f07b7bcaec72a19c12afbcd55442bfa057a6bb26de6d147c6a11`, split `43f8dc393b9686d4cae2bee1d7f4cedcb432ecf5143141afa1b6f34a2f31212b`, seed=20261012;
  환경: {"python": "3.12.14", "kiwipiepy": "0.23.2", "kiwipiepy_model": "0.23.0", "pydantic": "2.14.1", "model": null}
- selective_rule: git `73a9fcc379d37729cbe1ec8df8bbcb340511d28f`, source hash `b6ee792476f148a0e3eb4ac37002ad23d1c194f6123f8b2db793b05f22b73e85`, dirty=False;
  protocol `1e62a3811ae0f07b7bcaec72a19c12afbcd55442bfa057a6bb26de6d147c6a11`, split `43f8dc393b9686d4cae2bee1d7f4cedcb432ecf5143141afa1b6f34a2f31212b`, seed=20261012;
  환경: {"python": "3.12.14", "kiwipiepy": "0.23.2", "kiwipiepy_model": "0.23.0", "pydantic": "2.14.1", "model": null}

## 관측된 기각과 한계

- always_typed_patch: `케이크`, 제출 1, 최종 채택=False. 원장 trace의 실제 피드백 참조.
- always_typed_patch: `가습기`, 제출 1, 최종 채택=False. 원장 trace의 실제 피드백 참조.
- always_typed_patch: `김치`, 제출 1, 최종 채택=False. 원장 trace의 실제 피드백 참조.
- always_typed_patch: `아답터`, 제출 2, 최종 채택=True. 원장 trace의 실제 피드백 참조.
- selective_rule: `케이크`, 제출 1, 최종 채택=False. 원장 trace의 실제 피드백 참조.
- selective_rule: `아답터`, 제출 2, 최종 채택=True. 원장 trace의 실제 피드백 참조.
- 기존 v1의 공개 fixture만 평가했다. held-out·외부 도메인·LLM 능력 증거는 없다.
- span/형태 관계는 완전한 의미 타당성 판정이 아니다. Phase 2에서 독립 근거 검증이 필요하다.
- rewrite_query, switch_or_fuse_retriever, rerank 실행과 LLM 비교는 Phase 1에서 미지원/미실행이다.
- detector 기준은 기존 사전 지정값이며 latency 항 제외는 사후 버전 변경이다. 비용 차이는 모델 호출 절감의 증거가 아니다.
- gate budget은 제출 횟수 제한이다. 큰 corpus의 전체 재색인 시간 상한을 보장하지 않는다.
