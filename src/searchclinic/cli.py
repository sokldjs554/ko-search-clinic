"""CLI 진입점.

clinic analyze    : 텍스트의 형태소 분석 파이프라인을 보여준다
clinic search     : 현재(빈) 설정으로 검색해 본다
clinic evaluate   : 평가셋 전체를 채점한다 (치유 전 상태)
clinic diagnose   : 실패 질의 하나를 진료한다 (진료 기록 출력)
clinic heal       : 전체 실패 질의를 순회 치유하고 리포트/원장을 만든다
clinic demo-trap  : 과잉 동의어가 회귀 게이트에 기각되는 것을 시연한다
clinic export-es  : 채택된 설정을 Elasticsearch nori 설정 JSON으로 렌더링한다
clinic build-vectors : 임베딩 모델로 색인 어휘의 벡터 캐시를 생성한다
"""

from __future__ import annotations

import argparse
import sys
import unicodedata

from searchclinic.analysis.vectors import DEFAULT_MODEL
from searchclinic.doctor import ENGINES


def _pad(text: str, width: int) -> str:
    """한글은 터미널에서 두 칸을 차지한다 — 글자 수로 맞추면 표가 어긋난다."""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - shown)


def _force_utf8_output() -> None:
    """표준 출력을 UTF-8로 고정한다.

    한국어 Windows에서 표준 출력이 파일이나 파이프로 넘어가면 파이썬은
    locale 기본값(cp949)으로 인코딩한다. 이 도구의 출력에는 `✅`·`→`·`⚠️`가
    들어 있어 그 순간 UnicodeEncodeError로 죽는다 —
    `clinic heal > report.md`처럼 아주 흔한 사용법이 터진다는 뜻이다.

    콘솔에 직접 쓸 때는 파이썬이 이미 유니코드를 다루므로 영향이 없다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass  # 이미 닫혔거나 재설정할 수 없는 스트림 — 출력은 계속한다


def _build_executor(engine: str = "scripted"):
    from searchclinic.analysis.vectors import load_vectors_if_available
    from searchclinic.corpus import load_catalog, load_evalset
    from searchclinic.doctor import ClinicExecutor
    from searchclinic.index.engine import SearchEngine

    return ClinicExecutor(
        engine=SearchEngine(load_catalog()),
        evalset=load_evalset(),
        vectors=load_vectors_if_available() if engine == "vector" else None,
    )


def _warn_if_vectors_missing(engine: str) -> None:
    """벡터 의사를 불렀는데 캐시가 없으면 알린다.

    조용히 자모 규칙만 쓰는 상태로 떨어지면 '벡터를 켜고 돌린 결과'라는
    기록이 거짓이 된다. 세 엔진을 비교하는 프로젝트에서 이건 치명적이다.
    """
    if engine != "vector":
        return
    from searchclinic.analysis.vectors import CACHE_PATH, load_vectors_if_available

    if load_vectors_if_available() is None:
        print(
            f"벡터 캐시가 없습니다 ({CACHE_PATH}).\n"
            "임베딩 규칙이 꺼진 채로 돌아 'scripted'와 같은 결과가 나옵니다.\n"
            "먼저 생성하세요:\n"
            '  pip install -e ".[vector]"\n'
            "  clinic build-vectors",
            file=sys.stderr,
        )


def cmd_analyze(args: argparse.Namespace) -> int:
    from searchclinic.analysis import KoreanAnalyzer

    analyzer = KoreanAnalyzer()
    print(f"입력: {args.text}")
    for t in analyzer.explain(args.text):
        print(f"  {_pad(t['token'], 14)} {t['tag']:6s} ({t['origin']})")
    # 버려진 토큰을 감추면 "왜 0건인지"의 절반이 사라진다.
    # 아답터는 첫 음절 '아'가 감탄사로 오인돼 필터에서 빠지는 것이 핵심이다.
    for form, tag in analyzer.dropped(args.text):
        print(f"  {_pad(form, 14)} {tag:6s} (버려짐 — 내용어가 아님)")
    print(f"  → 색인 토큰: {analyzer.tokens(args.text) or '없음'}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    executor = _build_executor()
    payload = executor._tool_search_products(args.query, k=args.k)
    print(f"질의: {args.query} — {payload['total']}건")
    for r in payload["results"]:
        print(f"  {r['doc_id']}  {r['score']:7.3f}  {_pad(r['name'], 26)} (매칭: {', '.join(r['matched_terms'])})")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from searchclinic.corpus import failing_queries, healthy_queries, load_catalog
    from searchclinic.evaluation.metrics import evaluate_all, mean_ndcg, zero_result_rate
    from searchclinic.index.engine import SearchEngine

    engine = SearchEngine(load_catalog())
    fail = evaluate_all(engine, failing_queries())
    healthy = evaluate_all(engine, healthy_queries())
    print("### 치유 전 평가")
    print(f"- 건강 질의 {len(healthy)}건: 평균 nDCG {mean_ndcg(healthy):.3f}")
    print(f"- 실패 질의 {len(fail)}건: 평균 nDCG {mean_ndcg(fail):.3f} · 제로결과율 {zero_result_rate(fail):.0%}")
    print()
    for q, m in fail.items():
        print(f"  {_pad(q, 16)} nDCG={m.ndcg:.2f} recall={m.recall:.2f} 결과={m.n_results}")
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    from searchclinic.doctor import make_doctor, run_doctor_session

    executor = _build_executor(args.engine)
    known = [q.query for q in executor.evalset]
    if args.query not in known:
        print(f"평가셋에 없는 질의입니다: '{args.query}'", file=sys.stderr)
        print("채점할 정답(qrels)이 없으면 진료 결과를 검증할 수 없습니다.", file=sys.stderr)
        print("사용 가능한 질의:\n  " + "\n  ".join(known), file=sys.stderr)
        return 1
    _warn_if_vectors_missing(args.engine)
    try:
        doctor = make_doctor(args.engine)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    result = run_doctor_session(executor, doctor, args.query)
    print(f"진료 기록 — 질의 '{args.query}' (의사: {args.engine})")
    print("=" * 64)
    for line in result.transcript:
        print(line)
    print("=" * 64)
    print(f"결과: {'✅ 치유' if result.healed else '❌ 미치유'} · 진단={result.diagnosis_family or '없음'} · 제출 {result.attempts}회 · 턴 {result.n_turns}")
    return 0


def cmd_heal(args: argparse.Namespace) -> int:
    from searchclinic.evaluation import (
        render_ledger_json,
        render_ledger_markdown,
        render_report,
        run_clinic,
    )
    from searchclinic.patch.es_render import render_es_json

    _warn_if_vectors_missing(args.engine)
    try:
        report = run_clinic(doctor_name=args.engine)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    md = render_report(report)
    print(md)
    executor = report.final_executor
    print()
    print(render_ledger_markdown(executor.accepted))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md + "\n\n" + render_ledger_markdown(executor.accepted) + "\n")
        print(f"\n리포트 저장: {args.output}", file=sys.stderr)
    if args.ledger:
        with open(args.ledger, "w", encoding="utf-8") as f:
            f.write(render_ledger_json(executor.accepted) + "\n")
        print(f"원장 저장: {args.ledger}", file=sys.stderr)
    if args.es_output:
        with open(args.es_output, "w", encoding="utf-8") as f:
            f.write(render_es_json(executor.engine.config) + "\n")
        print(f"ES 설정 저장: {args.es_output}", file=sys.stderr)
    return 0


def cmd_demo_trap(args: argparse.Namespace) -> int:
    """과잉 동의어가 게이트에 기각되는 시연 — 이 프로젝트의 존재 이유."""
    from searchclinic.patch.gate import run_gate
    from searchclinic.patch.ir import Prescription

    executor = _build_executor()
    print("시연: '후라이팬'을 고치려고 과잉 동의어(프라이팬=후라이팬=팬)를 제출하면?\n")
    rx = Prescription(
        target_query="후라이팬",
        diagnosis_family="spelling_variant",
        reasoning="팬은 프라이팬의 준말이므로 함께 묶는다 (과잉 일반화 — 나쁜 처방의 예).",
        synonym_groups=[{"terms": ["프라이팬", "후라이팬", "팬"]}],
    )
    verdict, _ = run_gate(executor.engine, executor.evalset, rx)
    print(verdict.feedback())
    print("\n→ '팬' 토큰을 가진 팬미팅·선풍기 문서가 프라이팬 질의에 밀려 들어와")
    print("  다른 질의의 정밀도가 무너진다. 게이트가 전수 재실행으로 이를 잡는다.\n")

    print("올바른 최소 처방(프라이팬=후라이팬)을 제출하면?\n")
    rx2 = Prescription(
        target_query="후라이팬",
        diagnosis_family="spelling_variant",
        reasoning="후라이팬은 프라이팬의 비표준 표기. 최소 범위 동의어.",
        synonym_groups=[{"terms": ["프라이팬", "후라이팬"]}],
    )
    verdict2, _ = run_gate(executor.engine, executor.evalset, rx2)
    print(verdict2.feedback())
    return 0


def cmd_build_vectors(args: argparse.Namespace) -> int:
    """색인 어휘 + 평가셋 질의의 벡터를 뽑아 저장소에 커밋할 캐시를 만든다.

    이 명령만 임베딩 모델을 필요로 한다. 한 번 돌려 캐시를 커밋해 두면
    이후 `--engine vector`는 모델 없이도 **같은 수치를 재현**한다.
    """
    from searchclinic.analysis.vectors import (
        CACHE_PATH,
        CachedVectors,
        SentenceTransformerBackend,
    )
    from searchclinic.corpus import load_catalog, load_evalset
    from searchclinic.index.engine import SearchEngine

    engine = SearchEngine(load_catalog())
    # 색인 어휘 + 질의 원문·토큰까지 넣는다. 의사는 질의어로 유사도를
    # 물어보므로, 어휘만 넣으면 정작 기준어가 캐시에 없다.
    tokens = list(engine.vocabulary())
    for eq in load_evalset():
        tokens.append(eq.query)
        tokens.append(eq.query.replace(" ", ""))
        tokens.extend(engine.analyzer.tokens(eq.query))
    tokens = [t for t in tokens if t.strip()]

    try:
        backend = SentenceTransformerBackend(args.model)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"모델 {args.model}로 {len(set(tokens))}개 토큰을 임베딩합니다...", file=sys.stderr)
    cache = CachedVectors.build(backend, tokens, model=args.model)
    out = args.output or CACHE_PATH
    cache.save(out)
    size = __import__("pathlib").Path(out).stat().st_size
    print(f"벡터 캐시 저장: {out} ({len(cache)}개 토큰, {size/1024:.0f}KB)")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """검색 품질 기준선을 쓰거나(--write) 대조한다(기본).

    CI가 부르는 명령이다. 회귀가 있으면 종료 코드 1을 돌려주고, 그것이
    빌드를 빨간불로 만든다 — 진료 게이트가 처방을 기각하는 것과 같은 일을
    커밋 단위로 하는 셈이다.
    """
    import os

    from searchclinic.corpus import load_catalog, load_evalset
    from searchclinic.evaluation.baseline import (
        BASELINE_PATH,
        compare,
        load_baseline,
        write_baseline,
    )
    from searchclinic.index.engine import SearchEngine

    engine = SearchEngine(load_catalog())
    evalset = load_evalset()
    path = args.path or BASELINE_PATH

    if args.write:
        payload = write_baseline(engine, evalset, path)
        print(f"기준선 저장: {path} ({len(payload['queries'])}질의, 평균 nDCG {payload['mean_ndcg']:.4f})")
        return 0

    try:
        baseline = load_baseline(path)
    except FileNotFoundError:
        print(
            f"기준선 파일이 없습니다: {path}\n  clinic baseline --write 로 먼저 만드세요.",
            file=sys.stderr,
        )
        return 1

    report = compare(engine, evalset, baseline)
    print(report.summary())

    # GitHub Actions에서 돌면 요약 패널에 표를 남긴다. 로그를 스크롤해
    # 찾아야 하는 결과는 아무도 안 본다.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(report.markdown() + "\n")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report.markdown() + "\n")
        print(f"\n리포트 저장: {args.output}", file=sys.stderr)

    return 0 if report.ok else 1


def cmd_vector_probe(args: argparse.Namespace) -> int:
    """벡터 캐시가 정답 쌍과 쓰레기 쌍을 가를 수 있는지 잰다 (모델 불필요).

    임계값을 고르기 전에 도는 자리다. 여기서 "분리 불가"가 나오면
    `VECTOR_THRESHOLD`를 어떻게 잡아도 결과가 같다 — 실제로 그랬고,
    그 판정을 명령 하나로 재현할 수 있어야 결론을 믿을 수 있다.
    """
    from searchclinic.analysis.probe import render_probe_markdown
    from searchclinic.analysis.vectors import CACHE_PATH, load_vectors_if_available
    from searchclinic.corpus import load_catalog
    from searchclinic.index.engine import SearchEngine

    path = args.cache or CACHE_PATH
    vectors = load_vectors_if_available(path)
    if vectors is None:
        print(
            f"벡터 캐시가 없습니다: {path}\n  clinic build-vectors 로 먼저 생성하세요.",
            file=sys.stderr,
        )
        return 1

    vocabulary = sorted(SearchEngine(load_catalog()).vocabulary())
    md = render_probe_markdown(vectors, vocabulary)
    print(md)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print(f"\n검사 결과 저장: {args.output}", file=sys.stderr)
    return 0


def cmd_es_verify(args: argparse.Namespace) -> int:
    """렌더된 nori 설정을 실제 ES에 물려 로컬 결과와 대조한다.

    "1:1로 대응하도록 설계했다"는 렌더러의 주장을 실측으로 확인하는 자리다.
    """
    from searchclinic.corpus import load_catalog, load_evalset
    from searchclinic.es import (
        ESClient,
        ESError,
        ElasticsearchEngine,
        render_verification_markdown,
        verify,
    )
    from searchclinic.evaluation import run_clinic

    # 자격 증명은 ES_API_KEY / ES_USERNAME+ES_PASSWORD 환경 변수로 받는다.
    # 명령줄 인자로 두면 셸 히스토리와 프로세스 목록에 남는다.
    client = ESClient(args.url)
    try:
        info = client.ping()
        if not client.has_nori():
            print(
                "이 Elasticsearch에 analysis-nori 플러그인이 없습니다.\n"
                "docker/ 아래의 이미지로 띄우세요:\n"
                "  docker compose -f docker/docker-compose.yml up -d --build",
                file=sys.stderr,
            )
            return 1
    except ESError as e:
        print(str(e), file=sys.stderr)
        return 1

    version = info.get("version", {}).get("number", "?")
    auth = "인증됨" if client.authenticated else "인증 없음(로컬)"
    print(
        f"Elasticsearch {version} 연결됨 · analysis-nori 확인 · {auth}",
        file=sys.stderr,
    )

    _warn_if_vectors_missing(args.engine)
    print(f"'{args.engine}' 의사로 치유를 실행해 채택 설정을 만듭니다...", file=sys.stderr)

    def _tick(i, total, query, session):
        mark = "✅" if session.healed else "❌"
        print(
            f"  [{i}/{total}] {mark} {query} (제출 {session.attempts}회 · 턴 {session.n_turns})",
            file=sys.stderr,
            flush=True,
        )

    try:
        report = run_clinic(doctor_name=args.engine, on_progress=_tick)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    local = report.final_executor.engine

    es = ElasticsearchEngine(client, load_catalog(), local.config, index=args.index)
    print(f"ES 인덱스 '{args.index}' 생성 및 색인...", file=sys.stderr)
    try:
        es.reindex()
    except ESError as e:
        print(str(e), file=sys.stderr)
        return 1

    result = verify(local, es, load_evalset(), es_version=version)
    md = render_verification_markdown(result)
    print(md)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print(f"\n검증 리포트 저장: {args.output}", file=sys.stderr)
    if not args.keep:
        client.delete_index(args.index)
    return 0


def cmd_export_es(args: argparse.Namespace) -> int:
    from searchclinic.evaluation import run_clinic
    from searchclinic.patch.es_render import render_es_json

    print("스크립트 의사로 치유를 실행해 설정을 만든 뒤 렌더링합니다...", file=sys.stderr)
    report = run_clinic(doctor_name="scripted")
    text = render_es_json(report.final_executor.engine.config)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"저장: {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        prog="clinic", description="ko-search-clinic — 한국어 검색 품질 자가 치유"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="형태소 분석 파이프라인 확인")
    p.add_argument("text")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("search", help="현재 설정으로 검색")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("evaluate", help="치유 전 평가셋 채점")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("diagnose", help="실패 질의 하나 진료")
    p.add_argument("query")
    p.add_argument("--engine", choices=list(ENGINES), default="scripted")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("heal", help="전체 실패 질의 순회 치유 + 리포트")
    p.add_argument("--engine", choices=list(ENGINES), default="scripted")
    p.add_argument("--output", help="마크다운 리포트 저장 경로")
    p.add_argument("--ledger", help="패치 원장(JSON) 저장 경로")
    p.add_argument("--es-output", help="치유 후 ES 설정(JSON) 저장 경로")
    p.set_defaults(func=cmd_heal)

    p = sub.add_parser("demo-trap", help="과잉 동의어 기각 시연")
    p.set_defaults(func=cmd_demo_trap)

    p = sub.add_parser("export-es", help="치유 결과를 ES nori 설정으로 렌더링")
    p.add_argument("--output")
    p.set_defaults(func=cmd_export_es)

    p = sub.add_parser(
        "build-vectors", help="임베딩 모델로 어휘 벡터 캐시 생성 (1회, 모델 필요)"
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--output", help="캐시 저장 경로 (기본: 패키지 내 data/vectors.json)")
    p.set_defaults(func=cmd_build_vectors)

    p = sub.add_parser(
        "baseline", help="검색 품질 기준선 대조 (회귀면 종료 코드 1) — CI가 부른다"
    )
    p.add_argument("--write", action="store_true", help="현재 상태로 기준선을 새로 쓴다")
    p.add_argument("--path", help="기준선 파일 경로 (기본: docs/BASELINE.json)")
    p.add_argument("--output", help="대조 리포트(마크다운) 저장 경로")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser(
        "vector-probe", help="벡터 캐시의 분리 가능성·허브 구조 검사 (모델 불필요)"
    )
    p.add_argument("--cache", help="검사할 캐시 경로 (기본: 패키지 내 data/vectors.json)")
    p.add_argument("--output", help="검사 결과(마크다운) 저장 경로")
    p.set_defaults(func=cmd_vector_probe)

    p = sub.add_parser(
        "es-verify", help="렌더된 nori 설정을 실제 Elasticsearch에서 재검증"
    )
    p.add_argument("--url", default="http://localhost:9200")
    p.add_argument("--engine", choices=list(ENGINES), default="scripted")
    p.add_argument("--index", default="ko-search-clinic")
    p.add_argument("--output", help="검증 리포트(마크다운) 저장 경로")
    p.add_argument(
        "--keep", action="store_true", help="검증 후 인덱스를 지우지 않고 남긴다"
    )
    p.set_defaults(func=cmd_es_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
