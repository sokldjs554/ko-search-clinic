"""진료 한 건을 파이썬에서 직접 돌려 보는 예제.

CLI 없이 라이브러리로 쓰는 법과, 게이트가 처방을 어떻게 판정하는지를
한 화면에서 보여준다.

    python examples/heal_one_query.py
"""

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor import ClinicExecutor, ScriptedDoctor
from searchclinic.doctor.loop import run_doctor_session
from searchclinic.evaluation.metrics import evaluate_query
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.es_render import render_es_json

QUERY = "티슈"

evalset = load_evalset()
executor = ClinicExecutor(engine=SearchEngine(load_catalog()), evalset=evalset)
target = next(q for q in evalset if q.query == QUERY)

before = evaluate_query(executor.engine, target)
print(f"진료 전 — '{QUERY}': {before.n_results}건, nDCG {before.ndcg:.2f}")
print()

result = run_doctor_session(executor, ScriptedDoctor(), QUERY)
for line in result.transcript:
    print(line)

after = evaluate_query(executor.engine, target)
print()
print(f"진료 후 — '{QUERY}': {after.n_results}건, nDCG {after.ndcg:.2f}")
print(f"치유: {result.healed} · 진단: {result.diagnosis_family}")

if executor.accepted:
    print("\n채택된 설정을 Elasticsearch nori 설정으로 렌더링하면:\n")
    print(render_es_json(executor.engine.config)[:600] + " ...")
