### 지식 검색 품질 — `bm25` (top-5)

- 적중률(관련 문서 1건 이상): **25%**
- recall@5: 0.115 · precision@5: 0.113 · MRR: 0.167

| 질의 | 계열 | 검색된 문서 | 관련 |
|---|---|---|---|
| ❌ 후라이팬 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 케잌 주문 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 도너츠 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 쥬스 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 소세지 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 카페트 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 초콜렛 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 리모콘 | spelling_variant | K012 K011 K009 K016 K001 | 0/3 |
| ❌ 블루투스 스피커 | cross_script | K012 K011 K009 K016 K001 | 0/2 |
| ❌ 텀블러 | cross_script | K012 K009 K011 K001 K005 | 0/2 |
| ❌ 핸드폰 | synonym_gap | K012 K011 K009 K016 K001 | 0/2 |
| ❌ 츄리닝 | synonym_gap | K012 K011 K009 K016 K001 | 0/2 |
| ✅ 티슈 | compound_locked | K012 K011 **K009** K001 K006 | 1/3 |
| ✅ 머스캣 | compound_locked | K012 K011 **K009** K001 K006 | 1/3 |
| ✅ 아답터 | garbage_split | **K001** **K016** K012 K009 **K011** | 3/6 |
| ✅ 백팩 | garbage_split | **K001** K012 **K011** **K005** **K016** | 4/6 |

### 지식 검색 품질 — `dense` (top-5)

- 적중률(관련 문서 1건 이상): **75%**
- recall@5: 0.271 · precision@5: 0.175 · MRR: 0.591
- ⚠️ **벡터 캐시가 지식베이스 어휘의 7%만 안다.** 이 수치는 임베딩의 실력이 아니라 캐시의 결손을 반영한다 — `clinic build-vectors`로 캐시를 다시 만들면 달라진다.

| 질의 | 계열 | 검색된 문서 | 관련 |
|---|---|---|---|
| ✅ 후라이팬 | spelling_variant | **K006** K011 K012 K008 K016 | 1/3 |
| ✅ 케잌 주문 | spelling_variant | **K006** K011 K012 K008 K016 | 1/3 |
| ✅ 도너츠 | spelling_variant | **K006** K011 K012 K008 K016 | 1/3 |
| ✅ 쥬스 | spelling_variant | **K006** K011 K012 K009 K008 | 1/3 |
| ✅ 소세지 | spelling_variant | **K006** K011 K012 K008 K016 | 1/3 |
| ✅ 카페트 | spelling_variant | **K006** K011 K012 K008 K009 | 1/3 |
| ✅ 초콜렛 | spelling_variant | **K006** K011 K012 K009 K016 | 1/3 |
| ✅ 리모콘 | spelling_variant | **K006** K011 K012 K016 K008 | 1/3 |
| ✅ 블루투스 스피커 | cross_script | K008 K006 K011 K012 **K010** | 1/2 |
| ❌ 텀블러 | cross_script | K006 K005 K011 K012 K009 | 0/2 |
| ❌ 핸드폰 | synonym_gap | K006 K011 K012 K014 K016 | 0/2 |
| ✅ 츄리닝 | synonym_gap | K006 K011 K012 **K008** K016 | 1/2 |
| ❌ 티슈 | compound_locked | K006 K011 K012 K016 K008 | 0/3 |
| ❌ 머스캣 | compound_locked | K006 K011 K012 K008 K016 | 0/3 |
| ✅ 아답터 | garbage_split | K006 **K011** K012 K009 **K016** | 2/6 |
| ✅ 백팩 | garbage_split | K006 **K011** K012 **K016** K010 | 2/6 |

### 지식 검색 품질 — `hybrid` (top-5)

- 적중률(관련 문서 1건 이상): **75%**
- recall@5: 0.260 · precision@5: 0.188 · MRR: 0.288
- ⚠️ **벡터 캐시가 지식베이스 어휘의 7%만 안다.** 이 수치는 임베딩의 실력이 아니라 캐시의 결손을 반영한다 — `clinic build-vectors`로 캐시를 다시 만들면 달라진다.

| 질의 | 계열 | 검색된 문서 | 관련 |
|---|---|---|---|
| ✅ 후라이팬 | spelling_variant | K012 K011 **K006** K009 K016 | 1/3 |
| ✅ 케잌 주문 | spelling_variant | K012 K011 **K006** K016 K009 | 1/3 |
| ✅ 도너츠 | spelling_variant | K012 K011 **K006** K009 K016 | 1/3 |
| ✅ 쥬스 | spelling_variant | K012 K011 **K006** K009 K016 | 1/3 |
| ✅ 소세지 | spelling_variant | K012 K011 **K006** K016 K001 | 1/3 |
| ✅ 카페트 | spelling_variant | K012 K011 **K006** K009 K016 | 1/3 |
| ✅ 초콜렛 | spelling_variant | K012 K011 **K006** K009 K016 | 1/3 |
| ✅ 리모콘 | spelling_variant | K012 K011 **K006** K016 K009 | 1/3 |
| ❌ 블루투스 스피커 | cross_script | K012 K011 K006 K016 K009 | 0/2 |
| ❌ 텀블러 | cross_script | K012 K011 K005 K009 K006 | 0/2 |
| ❌ 핸드폰 | synonym_gap | K012 K011 K006 K016 K009 | 0/2 |
| ❌ 츄리닝 | synonym_gap | K012 K011 K006 K009 K016 | 0/2 |
| ✅ 티슈 | compound_locked | K012 K011 K006 **K009** K016 | 1/3 |
| ✅ 머스캣 | compound_locked | K012 K011 K006 K001 **K009** | 1/3 |
| ✅ 아답터 | garbage_split | K012 **K011** **K016** K009 K006 | 2/6 |
| ✅ 백팩 | garbage_split | **K011** K012 **K016** K006 **K002** | 3/6 |
