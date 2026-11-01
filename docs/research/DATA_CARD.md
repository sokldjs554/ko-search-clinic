# Phase 0–1 data card와 split 계약

원천은 기존 수작업 상품 카탈로그와 Kiwi 실패 재현용 평가셋이다.
`src/searchclinic/corpus/catalog.py`, `evalset.py`를 그대로 사용한다.
공개 fixture에는 개인 사용자 로그가 없으며 실제 서비스 표본이 아니다.
v1 qrels는 정확 문서=2, 관련 문서=1이다. 원래 분모는 healthy 20,
failing 16, 전체 36이며 사전 데이터 계약으로 고정하고 감사 JSON으로 확인한다.
실패 계열/처방 정답은 기존 evalset의 라벨을 그대로 평가 전용으로 사용한다.

기존 개발·README·결과에서 이미 노출된 전체 데이터를 controlled-v1/dev로
지정한다. train/test는 빈 집합이다. 이번 작업에는 held-out 성능이 없다.
정규화는 Unicode NFKC, casefold, whitespace collapse를 사용한다.
query_id는 정규화 질의의 SHA256에서 생성하며 seed와 무관하게 안정적이다.
각 row에 source, split, query_id/query, document_ids, template_id,
synonym_group_ids를 필수 선언한다. document_ids는 해당 질의의 qrels 문서
집합이며 정책에는 제공하지 않는다. corpus hash와 split hash를 모두 저장한다.

split 누수 검사는 train/dev/test 사이에서 query, query_id, document_id,
template_id, synonym_group_id 공유를 차단한다. 중복 query ID·미지 문서·
비어 있는 메타데이터·평가셋 누락도 거부한다. v1에서는 모든 관계가 dev
안에 있으므로 누수 검사는 통과할 수 있으나 독립 test가 있다는 뜻은 아니다.
새 표현이나 도메인은 이 manifest에 이름만 바꿔 넣지 않는다.

기존 라벨은 검색 실패 유무와 실패 계열을 측정하는 평가 정답이다. 실패
탐지기는 family·expected_patch_kinds·qrels·baseline 품질을 읽지 않는다.
반환 문서 수는 전체 corpus hit count가 아니라 기존 search가 반환한 top-10
개수다. agreement, conflict, grounding은 이번 단계에 측정원이 없어서 null이다.

주요 편향: 소규모 수작업 상품 도메인, 같은 개념 반복, 사전에 선택한 실패,
공개된 정답, 분석기 버전 의존성. 지연은 실행 환경에 종속된다.
원문의 배포 라이선스가 별도로 명시돼 있지 않아 외부 재배포 권리 판단은
미확인이다. 학습 데이터나 실제 서비스 일반화 근거로 주장하지 않는다.
