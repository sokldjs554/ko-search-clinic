# Phase 0–1 실제 원격 검증

[Draft PR #1](https://github.com/sokldjs554/ko-search-clinic/pull/1)을
feature 브랜치에서 main으로 열었다. 병합하지 않았다.

## 보존 기준 a0fc8c7의 실제 실행

- PR head: `a0fc8c7abe8a04d932de382e28e5ccd93b3cdc1f`
- base main: `80ea3bcf2fffb395b27abc3d38db4e9876a9c2d1`
- 실제 checkout: `0a4476d49428582398ea7a066c873e45f965bda0`
- [CI 실행 38211127720](https://github.com/sokldjs554/ko-search-clinic/actions/runs/38211127720)

checkout은 GitHub의 PR merge commit이다. job 로그의 git log -1 출력으로
세 job 모두 같은 SHA를 확인했다. PR head SHA와 혼동하지 않는다.

| 실제 job | 결과 | 테스트 | skip |
|---|---|---|---|
| Ubuntu | success | 333 passed | 2 skipped |
| Windows | success | 333 passed | 2 skipped |
| 검색 품질 게이트 | success | clinic baseline 및 연구 기준선 실행 | failure() 조건이 거짓이어서 실패 시 지표 출력 단계 생략 |

테스트 skip은 CI 설치 extras에 없는 pyarrow의 scale module과 psycopg2의
PostgreSQL module이다. 원격의 skip과 로컬의 Spark/PostgreSQL skip은
서로 다른 설치 환경이다. 후속 workflow는 pytest -rs로 사유를 직접 출력한다.

근거: `artifacts/research/remote-ci/run-38211127720/summary.json`과 job별
evidence log. [연구 artifact 11728974687](https://github.com/sokldjs554/ko-search-clinic/actions/runs/38211127720/artifacts/11728974687)
업로드가 성공했다. GitHub digest는
`46fd397d1d2c90edd8cae388cbd8468229f37ac7fcff23b10b4e9d94da6f34ea`이다.

artifact ZIP 로컬 다운로드는 한 번 시도했으며 `curl: (22) The requested
URL returned error: 403`으로 막혔다. 반복하지 않았다. 따라서 ZIP 내용의
로컬 read-back 검증은 미확인이다. 다운로드 상태를 별도 JSON에 기록했다.
서버의 업로드 digest 확인과 로컬 ZIP 재검증을 구분한다.

## 후속 버전 검증 경계

phase01-v2는 기존 버전과 별도 root에서 실행한다. workflow는 두 버전을
분리 실행/업로드하고 각 run의 실제 git_sha, source_hash, protocol_hash,
split/evalset_hash, summary와 costs를 RESEARCH_PROVENANCE JSON 로그에 남긴다.
후속 head의 원격 결과는 해당 Actions 실행의 checkout 로그/JSON과 별도
마무리 보고로 확인한다. 위 a0fc8c7 결과를 후속 SHA의 통과로 재사용하지 않는다.
