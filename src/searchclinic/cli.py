"""CLI 진입점.

clinic analyze    : 텍스트의 형태소 분석 파이프라인을 보여준다
clinic search     : 현재(빈) 설정으로 검색해 본다
clinic evaluate   : 평가셋 전체를 채점한다 (치유 전 상태)
clinic diagnose   : 실패 질의 하나를 진료한다 (진료 기록 출력)
clinic heal       : 전체 실패 질의를 순회 치유하고 리포트/원장을 만든다
clinic demo-trap  : 과잉 동의어가 회귀 게이트에 기각되는 것을 시연한다
clinic export-es  : 채택된 설정을 Elasticsearch nori 설정 JSON으로 렌더링한다
"""

from __future__ import annotations

import argparse
import sys
import unicodedata


def _pad(text: str, width: int) -> str:
    """한글은 터미널에서 두 칸을 차지한다 — 글자 수로 맞추면 표가 어긋난다."""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - shown)


def _build_executor():
    from searchclinic.corpus import load_catalog, load_evalset
    from searchclinic.doctor import ClinicExecutor
    from searchclinic.index.engine import SearchEngine

    return ClinicExecutor(engine=SearchEngine(load_catalog()), evalset=load_evalset())


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

    executor = _build_executor()
    known = [q.query for q in executor.evalset]
    if args.query not in known:
        print(f"평가셋에 없는 질의입니다: '{args.query}'", file=sys.stderr)
        print("채점할 정답(qrels)이 없으면 진료 결과를 검증할 수 없습니다.", file=sys.stderr)
        print("사용 가능한 질의:\n  " + "\n  ".join(known), file=sys.stderr)
        return 1
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
    p.add_argument("--engine", choices=["scripted", "claude"], default="scripted")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("heal", help="전체 실패 질의 순회 치유 + 리포트")
    p.add_argument("--engine", choices=["scripted", "claude"], default="scripted")
    p.add_argument("--output", help="마크다운 리포트 저장 경로")
    p.add_argument("--ledger", help="패치 원장(JSON) 저장 경로")
    p.add_argument("--es-output", help="치유 후 ES 설정(JSON) 저장 경로")
    p.set_defaults(func=cmd_heal)

    p = sub.add_parser("demo-trap", help="과잉 동의어 기각 시연")
    p.set_defaults(func=cmd_demo_trap)

    p = sub.add_parser("export-es", help="치유 결과를 ES nori 설정으로 렌더링")
    p.add_argument("--output")
    p.set_defaults(func=cmd_export_es)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
