### 진료 결과 — 의사: `vector`

| 질의 | 정답 계열 | 진단 | 처방 유형 | 치유 | nDCG 전→후 | 시도 |
|---|---|---|---|---|---|---|
| 후라이팬 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 케잌 주문 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 도너츠 | spelling_variant | synonym_gap ⚠️오진 | — | ❌ | 0.00 → 0.00 | 1 |
| 쥬스 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 소세지 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 카페트 | spelling_variant | synonym_gap ⚠️오진 | synonym | ✅ | 0.00 → 0.39 | 1 |
| 초콜렛 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 리모콘 | spelling_variant | spelling_variant | synonym | ✅ | 0.00 → 1.00 | 1 |
| 블루투스 스피커 | cross_script | synonym_gap ⚠️오진 | — | ❌ | 0.50 → 0.50 | 1 |
| 텀블러 | cross_script | synonym_gap ⚠️오진 | — | ❌ | 0.61 → 0.61 | 1 |
| 핸드폰 | synonym_gap | synonym_gap | synonym | ✅ | 0.00 → 0.67 | 1 |
| 츄리닝 | synonym_gap | synonym_gap | — | ❌ | 0.00 → 0.00 | 1 |
| 티슈 | compound_locked | compound_locked | compound_expansion | ✅ | 0.00 → 1.00 | 1 |
| 머스캣 | compound_locked | synonym_gap ⚠️오진 | — | ❌ | 0.00 → 0.00 | 1 |
| 아답터 | garbage_split | synonym_gap ⚠️오진 | — | ❌ | 0.00 → 0.00 | 1 |
| 백팩 | garbage_split | synonym_gap ⚠️오진 | — | ❌ | 0.00 → 0.00 | 1 |

- 치유율: **56%** (9/16)
- 진단 정확도: **56%** — 계열 라벨과 일치 (고쳤어도 이유가 틀리면 오진)
- 처방 적합성: **56%** — 정답 처방 유형을 전부 포함
- 실패셋 평균 nDCG: **0.070 → 0.573**
- 실패셋 제로결과율: **81% → 25%**
- 건강셋 평균 nDCG: 0.995 → 0.995 · 회귀 질의: **0건** (게이트 보증)
- 채택된 처방: 9건

### 패치 원장 — 모든 항목에 채택 증거가 붙어 있다

| # | 표적 질의 | 계열 | 패치 | 표적 nDCG | 결과 수 | 시도 |
|---|---|---|---|---|---|---|
| 1 | 후라이팬 | spelling_variant | 동의어(프라이팬 = 후라이팬) | 0.00 → 1.00 | 0 → 2 | 1 |
| 2 | 케잌 주문 | spelling_variant | 동의어(케이크 = 케잌) | 0.00 → 1.00 | 0 → 2 | 1 |
| 3 | 쥬스 | spelling_variant | 동의어(주스 = 쥬스) | 0.00 → 1.00 | 0 → 2 | 1 |
| 4 | 소세지 | spelling_variant | 동의어(소시지 = 소세지) | 0.00 → 1.00 | 0 → 2 | 1 |
| 5 | 카페트 | synonym_gap | 동의어(방지 = 카페트) | 0.00 → 0.39 | 0 → 3 | 1 |
| 6 | 초콜렛 | spelling_variant | 동의어(초콜릿 = 초콜렛) | 0.00 → 1.00 | 0 → 3 | 1 |
| 7 | 리모콘 | spelling_variant | 동의어(리모컨 = 리모콘) | 0.00 → 1.00 | 0 → 2 | 1 |
| 8 | 핸드폰 | synonym_gap | 동의어(휴대폰 = 핸드폰) | 0.00 → 0.67 | 0 → 2 | 1 |
| 9 | 티슈 | compound_locked | 분해확장(물티슈 → 물+티슈) | 0.00 → 1.00 | 0 → 2 | 1 |
