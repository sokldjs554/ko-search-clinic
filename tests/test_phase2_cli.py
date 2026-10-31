import hashlib
import importlib.util
import json
import os
import subprocess
import sys


def test_prepare_does_not_open_labels_or_run_evaluator(tmp_path):
    assert importlib.util.find_spec('searchclinic.research.phase2.__main__'), 'free CLI missing'
    corpus=tmp_path/'corpus.json'
    stimuli=tmp_path/'stimuli.json'
    corpus.write_text(json.dumps({'documents':[{'doc_id':'X','name':'수문','description':'물 조절','category':'fixture'}]}),encoding='utf-8')
    stimuli.write_text(json.dumps({'queries':[{'query_id':'x','query':'수믄'}]}),encoding='utf-8')
    out=tmp_path/'prepared'
    command=[sys.executable,'-m','searchclinic.research.phase2','prepare',
        '--corpus',str(corpus),'--stimuli',str(stimuli),'--label-commitment','a'*64,'--out',str(out)]
    subprocess.run(command,check=True,env=os.environ,capture_output=True,text=True)
    sealed=json.loads((out/'rules-preparation.json').read_text(encoding='utf-8'))
    assert set(sealed['body']['arms'])=={'rules_plus'}
    assert (out/'llm-requests.json').exists()
    assert not (out/'evaluation.json').exists()
    status=json.loads((out/'status.json').read_text(encoding='utf-8'))
    assert status['paid_calls']==0 and status['final_evaluation']=='not_run'
    assert status['shared_preparation_costs']['search_calls']>0
    assert hashlib.sha256((out/'rules-preparation.json').read_bytes()).hexdigest()
    repeat=subprocess.run(command,env=os.environ,capture_output=True,text=True)
    assert repeat.returncode!=0
