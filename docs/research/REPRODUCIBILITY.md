# Phase 0–1 재현

사전 프로토콜 커밋은 `6ec3b8dacba53b3bcd18704f2680567432dab531`이다.
runner는 그 커밋의 protocol.json과 현재 파일을 대조한다. Git history가 없는
소스 archive/설치 wheel만으로는 프로토콜 검증을 재현할 수 없다. 전체 Git
checkout에서 실행해야 하며 CI checkout도 fetch-depth=0으로 지정했다.

## 새 환경

```bash
git clone https://github.com/sokldjs554/ko-search-clinic.git
cd ko-search-clinic
git switch feat/selective-retrieval-repair-v2
python -m venv .venv
# Windows에서는 .venv/Scripts/python, POSIX에서는 .venv/bin/python 사용
.venv/bin/python -m pip install -r docs/research/environment.lock.txt -e .
.venv/bin/python -m pytest -q -m ""
.venv/bin/clinic baseline
.venv/bin/clinic research audit --root artifacts/reproduction-01
.venv/bin/clinic research prepare --root artifacts/reproduction-01
.venv/bin/clinic research baseline --root artifacts/reproduction-01
.venv/bin/clinic research report --root artifacts/reproduction-01
```

연구 최소 설치는 `pip install -c docs/research/constraints.txt -e .`이다.
테스트까지 포함하려면 `.[api,mcp,dev,scale]`을 사용한다. lock 파일은 이번
실제 설치 환경이다. Python/Kiwi/Pydantic 버전은 각 run에 기록된다.
유료 API 키나 embedding model 다운로드는 필요하지 않다.

각 비교는 새 root에서 실행한다. 동일 정책 run이 중복된 디렉터리는 보고서
생성을 거부하며, 기존 JSON/Markdown 파일을 덮어쓰지 않는다. 보고서 숫자는
질의별 JSON으로 다시 계산해 summary와 일치하는지 확인한다.

## 이 작업에서 실제 수행한 새 환경 재현

별도 `/workspace/clinic-repro-venv`를 만들었다. lock의 패키지들을 wheelhouse로
만든 뒤 `--no-index --find-links`로 설치하여 의존성을 설치한 뒤의 연구 실행은
네트워크 없이 재현했다. 이 환경의 run은
`artifacts/research/validation/runs/`에 보존했다. 원래 환경의 첫 run은
`artifacts/research/runs/`에 그대로 남긴다. 두 환경 판정 비교와 검증 명령의
실제 exit code는 `artifacts/research/verification/verification.json`에 저장한다.

기본 pytest는 slow marker를 제외한다. 이번 최종 검증은 `-m ""`로 slow
표본까지 실행했다. Spark 패키지와 PostgreSQL 서비스가 없는 테스트는
skip이며 통과로 세지 않는다. 실제 ES 연결·실제 LLM 실행은 하지 않았다.
샌드박스의 REST TestClient는 loopback 권한이 필요했다. 네트워크 권한으로
로컬 테스트를 실행했으며 테스트 자체에 유료 API 호출은 없다.

재생 테스트는 seed, 데이터, 실제 품질/선택/제출/호출 counts를 대조한다.
시간·UUID는 재생 signature에 포함하지 않는다. 실제 진단 latency는 정책의
효용 입력이므로 환경 부하로 효용이 0을 넘나들면 선택도 달라질 수 있다.
동일 seed만으로 모든 환경의 선택이 동일하다는 주장은 하지 않는다.

main의 기존 CI 실패와 Kiwi 변경 영향은 CURRENT_STATE_AUDIT.md에 보존했다.
이번 변경의 GitHub CI는 원격 실행 결과를 확인하기 전에는 통과로 기록하지 않는다.
