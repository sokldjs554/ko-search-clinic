"""Explicit posthoc DEVELOPMENT amendment: six unattempted original requests.

The original stopped run, its halted journal and permanent claim stay unchanged.
This module imports its one known settled call into a separate aggregate ledger;
it never resends that request. Only proven candidate-validation errors may become
terminal empty candidates. Every transport, billing or incomplete-response fault
still stops the batch. No labels are read here.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

ORIGINAL_PLAN = '135f26a43bb9dd1c9f942a6b446fb637783af55e79ea29b82a3ae499bbb14b6b'
PARENT_PLAN = '4263e1ef1da58d01190af596278b2b4c8608dab30d0f5eb08e05930791b1fe8c'
PARENT_ARTIFACT_SHA = 'd0764eb2c282c8f5611b26a865d07ffe5e5319c016f255b4afaa3130a6efa2fa'
PARENT_RAW_SHA = 'deb9e31a37d844e55f3272a0c529e4887722e3e2fcca3a552cfd4e9064f9192c'
PARENT_RECEIPT_SHA = '61e9ef3fb78e2db5babfde00729711e1150c99e74b50fd6c610ce2b0d4f93400'
PARENT_WORKFLOW = '0717ee6c2be8ba88d7002f0aff178c017d7ed6d9'
FAMILY = 'p2r3-gpt-' + ORIGINAL_PLAN + '-continuation-1'


def _api():
    from searchclinic.research.phase2 import provider, dev_comparison, generation
    from searchclinic.research.phase2.budget import DurableCallBudget
    from searchclinic.research.splits import digest
    return provider, dev_comparison, generation, DurableCallBudget, digest


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _cost(config, inputs, outputs):
    return (Decimal(config['input_usd_million']) * inputs + Decimal(config['output_usd_million']) * outputs) / Decimal(1_000_000)


def _journal_snapshot(path,experiment_hash,config):
    """Inspect authoritative journals read-only; never reopen them for mutation."""
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:row=connection.execute('SELECT identity,state FROM budget WHERE id=1').fetchone()
    finally:connection.close()
    _check(row is not None,'journal state missing')
    identity,state=json.loads(row[0]),json.loads(row[1])
    expected=dict(experiment_hash=experiment_hash,model=config['model'],
        input_usd_million=str(Decimal(config['input_usd_million']).normalize()),
        output_usd_million=str(Decimal(config['output_usd_million']).normalize()),
        max_calls=config['max_calls'],usd_limit=str(Decimal(config['usd_limit']).normalize()),
        max_input_tokens=config['max_input_tokens'])
    _check(identity==expected,'journal identity differs')
    return dict(spent_usd=state['spent'],reserved_usd=state['reserved'],calls=state['calls'],
                halted=state['halted'],entries=state['entries'])


def _accounting(context, receipt, response):
    provider, _, _, _, digest = _api()
    payload = provider.prepare_payload(context)
    _check(receipt['mode'] == 'live' and receipt['request_hash'] == digest(payload)
           and receipt['context_hash'] == digest(context) and receipt['model'] == provider.MODEL, 'receipt provenance mismatch')
    _check(receipt['transmission_attempts'] == 1 and receipt['confirmed_api_responses'] == 1
           and receipt['actual_api_calls'] == 1 and receipt['unknown_after_attempt'] == 0
           and receipt['http_status'] == 200 and receipt['billing_status'] == 'settled', 'unknown or unsuccessful parent/child accounting')
    usage = response['usage']
    inputs, outputs = usage['prompt_tokens'], usage['completion_tokens']
    _check(type(inputs) is int and type(outputs) is int and 0 <= inputs <= receipt['preflight']['byte_reservation_tokens']
           and 0 <= outputs <= 1500 and response['model'] == provider.MODEL, 'invalid measured usage or model')
    _check(receipt['provider_usage'] == {'prompt_tokens': inputs, 'completion_tokens': outputs}, 'receipt usage differs from response')
    cost = _cost(provider.CONFIG, inputs, outputs)
    _check(Decimal(str(receipt['api_cost_usd'])) == cost, 'receipt cost mismatch')
    return inputs, outputs, cost


def classify_receipt(context, receipt, response):
    """Reparse evidence; candidate validation is the sole nonfatal error class."""
    provider, _, generation, _, _ = _api()
    inputs, _, _ = _accounting(context, receipt, response)
    _check(inputs <= receipt['preflight']['admission_tokens'], 'actual input exceeds frozen admission allowance')
    _check(isinstance(response['choices'], list) and len(response['choices']) == 1, 'exactly one response choice required')
    choice = response['choices'][0]
    _check(choice['finish_reason'] == 'stop' and not choice['message'].get('refusal'), 'incomplete/refused response remains fatal')
    parsed = json.loads(choice['message']['content'])
    _check(type(parsed) is dict and set(parsed) == {'candidates'}, 'malformed candidate envelope remains fatal')
    try:
        candidates = generation.validate_candidates(context, parsed['candidates'])
    except (ValueError, TypeError, KeyError):
        _check(receipt['status'] == 'error' and receipt['candidates'] == [] and receipt['budget']['halted'] is True,
               'candidate error was not terminal in original provider')
        return 'candidate_error'
    _check(receipt['status'] == 'completed' and receipt['candidates'] == candidates, 'provider receipt differs from validated candidates')
    return 'completed'


def _evidence(original_plan_path, parent_root, parent_artifact_path, baseline_path, approval_reference):
    provider, dev, _, _, digest = _api()
    parent_root = Path(parent_root)
    original = _read(original_plan_path); parent = _read(parent_root/'plan.json')
    _check(original['plan_hash'] == digest(original['body']) == ORIGINAL_PLAN, 'original plan mismatch')
    _check(parent['plan_hash'] == digest(parent['body']) == PARENT_PLAN, 'parent execution plan mismatch')
    _check({k:v for k,v in original['body'].items() if k != 'execution_root'} ==
           {k:v for k,v in parent['body'].items() if k != 'execution_root'}, 'parent requests changed')
    _check(_sha(parent_artifact_path) == PARENT_ARTIFACT_SHA, 'authenticated parent artifact differs')
    baseline = dev._baseline(baseline_path)
    _check(_sha(baseline_path) == original['body']['baseline_file_sha256']
           and baseline['seal_hash'] == original['body']['baseline_seal_hash'], 'immutable baseline mismatch')
    selected = [q for q in original['body']['requests'] if q['selected']]
    _check(len(selected) == 7 and original['body']['config'] == provider.CONFIG, 'original seven/config required')
    first = selected[0]; qid = first['query_id']
    run = parent_root/'private/execution-registry'/PARENT_PLAN
    status = _read(run/'status.json')
    _check(status['status'] == 'stopped' and status['plan_hash'] == PARENT_PLAN and status['mode'] == 'live'
           and status['actual_api_calls'] == 1 and status['transmission_attempts'] == 1
           and status['confirmed_api_responses'] == 1 and status['unknown_after_attempt'] == 0
           and status['failed_query_id'] == qid and set(status['receipts']) == {qid}, 'parent must contain exactly first known attempt')
    file = (run/status['receipts'][qid]['file']).resolve()
    _check(file.is_relative_to(run.resolve()) and _sha(file) == status['receipts'][qid]['sha256'] == PARENT_RECEIPT_SHA, 'parent receipt anchor mismatch')
    receipt = _read(file)
    _check(receipt['budget']['calls'] == 1 and receipt['budget']['halted'] is True
           and set(receipt['budget']['entries']) == {qid}, 'parent halted ledger evidence differs')
    parent_journal=run/'receipts/calls.sqlite'
    _check(_journal_snapshot(parent_journal,digest({'experiment':PARENT_PLAN,'mode':'live'}),provider.CONFIG)==receipt['budget'],
           'parent authoritative halted journal differs from receipt')
    raw = parent_root/'raw-http'/(first['request_hash']+'.http-body.bin')
    meta_path = raw.with_name(first['request_hash']+'.http-meta.json'); meta = _read(meta_path)
    _check(_sha(raw) == meta['raw_sha256'] == PARENT_RAW_SHA and meta['request_hash'] == first['request_hash']
           and meta['http_status'] == 200 and meta['credential_echo_redacted'] is False, 'parent raw response anchor mismatch')
    response = _read(raw)
    contexts = {c['query_id']: c for c in baseline['body']['contexts']}
    _check(classify_receipt(contexts[qid], receipt, response) == 'candidate_error', 'parent error is not eligible for amendment')
    inputs, outputs, spent = _accounting(contexts[qid], receipt, response)
    _check(Decimal(receipt['budget']['spent_usd']) == spent and Decimal(receipt['budget']['reserved_usd']) == 0, 'parent cumulative accounting differs')
    claim = _read(parent_root/'global-claim.json')
    _check(claim == {'family': 'p2r3-gpt-'+ORIGINAL_PLAN, 'workflow_sha': PARENT_WORKFLOW,
                     'run_id': '38508730307', 'claim_acknowledged': True}, 'parent permanent claim evidence differs')
    _check(isinstance(approval_reference,str) and approval_reference.strip(), 'explicit continuation authorization reference required')
    reserved = sum((_cost(provider.CONFIG, q['preflight']['byte_reservation_tokens'], 1500) for q in selected[1:]), Decimal(0))
    _check(spent + reserved <= Decimal(provider.CONFIG['usd_limit']), 'parent plus all remaining calls exceed original USD budget')
    body = dict(schema_version=1, scope='synthetic_development_only', posthoc_development_amendment=True,
        amendment='candidate validation failures become terminal empty candidates; original failures preserved; no retries',
        family=FAMILY, original_plan_hash=ORIGINAL_PLAN, parent_plan_hash=PARENT_PLAN,
        parent_artifact_sha256=PARENT_ARTIFACT_SHA, parent_receipt_sha256=PARENT_RECEIPT_SHA,
        parent_raw_sha256=PARENT_RAW_SHA, parent_status_sha256=_sha(run/'status.json'),
        parent_journal_sha256=_sha(parent_journal),
        parent_claim_sha256=_sha(parent_root/'global-claim.json'), baseline_file_sha256=_sha(baseline_path),
        baseline_seal_hash=baseline['seal_hash'], source_sha=baseline['body']['source_sha'],
        source_hash=baseline['body']['source_hash'], continuation_module_sha256=_sha(__file__), config=provider.CONFIG,
        approval_reference=approval_reference, original_request_hashes=[q['request_hash'] for q in selected],
        remaining_request_hashes=[q['request_hash'] for q in selected[1:]],
        parent=dict(query_id=qid,request_hash=first['request_hash'],actual_calls=1,input_tokens=inputs,
                    output_tokens=outputs,spent_usd=str(spent),outcome='candidate_error'),
        remaining_reserved_usd=str(reserved),total_reserved_plus_parent_usd=str(spent+reserved))
    return body, baseline['body'], selected, receipt


def freeze_amendment(original_plan_path,parent_root,parent_artifact_path,baseline_path,output_path,*,approval_reference):
    _, _, generation, _, digest = _api()
    body, _, _, _ = _evidence(original_plan_path,parent_root,parent_artifact_path,baseline_path,approval_reference)
    amendment = {'amendment_hash':digest(body),'body':body}
    generation.write_once(output_path,amendment)
    return amendment


def verify_amendment(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path):
    _, _, _, _, digest = _api()
    amendment = _read(amendment_path)
    _check(set(amendment) == {'amendment_hash','body'} and amendment['amendment_hash'] == digest(amendment['body']), 'amendment seal mismatch')
    body, _, _, _ = _evidence(original_plan_path,parent_root,parent_artifact_path,baseline_path,amendment['body']['approval_reference'])
    _check(body == amendment['body'], 'amendment evidence/config drift')
    return amendment


def build_combined_records(baseline_body,receipts):
    provider, _, _, _, digest = _api()
    from searchclinic.research.costs import CostRecord
    records=[]
    for context, rule in zip(baseline_body['contexts'],baseline_body['arms']['rules_plus']):
        candidates=[]; error=None; costs=CostRecord()
        if rule['detection']['predicted_failure'] is True:
            receipt=receipts[context['query_id']]
            _check(receipt['candidate_outcome'] in ('completed','candidate_error'), 'unterminated query cannot seal')
            usage=receipt['provider_usage']
            costs=CostRecord(model_calls=1,input_tokens=usage['prompt_tokens'],output_tokens=usage['completion_tokens'],
                             latency_ms=receipt['latency_ms'],api_cost_usd=receipt['api_cost_usd'])
            if receipt['candidate_outcome']=='candidate_error':
                error={'type':'PosthocCandidateValidationFailure','provider_error_type':receipt['error_type'],
                       'amendment_family':FAMILY,'candidate_repair_or_retry':False}
            else:candidates=receipt['candidates']
        records.append(dict(query_id=context['query_id'],context_hash=digest(context),arm='llm',model=provider.MODEL,
                            detection=rule['detection'],candidates=candidates,error=error,worker_pid=0,costs=asdict(costs)))
    return records


def _child_evidence(out,index,query_id,request_hash,receipt,response):
    """Bind original receipt, parsed provider record and exact HTTP bytes."""
    out=Path(out);stem=hashlib.sha256(query_id.encode()).hexdigest()
    paths={'receipt':out/'children'/str(index)/(stem+'.result.json'),
           'provider_record':out/'children'/str(index)/(stem+'.result.raw.json'),
           'http_body':out/'raw-http'/(request_hash+'.http-body.bin'),
           'http_meta':out/'raw-http'/(request_hash+'.http-meta.json')}
    _check(_read(paths['receipt'])==receipt,'original child receipt changed')
    record=_read(paths['provider_record'])
    _check(record['mode']=='live' and record['request_hash']==request_hash and record['response']==response,'provider record mismatch')
    meta=_read(paths['http_meta'])
    _check(_sha(paths['http_body'])==meta['raw_sha256'] and meta['request_hash']==request_hash
           and meta['http_status']==200 and meta['credential_echo_redacted'] is False,'child exact HTTP provenance mismatch')
    _check(_read(paths['http_body'])==response,'exact HTTP bytes differ from provider record')
    return {key:{'path':path.relative_to(out).as_posix(),'sha256':_sha(path)} for key,path in paths.items()}


def run_continuation(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path,out,*,claim_callback,checkpoint):
    provider, _, generation, DurableCallBudget, digest = _api()
    amendment=verify_amendment(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path)
    body,baseline,selected,parent_receipt=_evidence(original_plan_path,parent_root,parent_artifact_path,baseline_path,amendment['body']['approval_reference'])
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    claim_callback(FAMILY) # Must verify existing parent claim and atomically create this sole continuation claim.
    generation.write_once(out/'amendment.json',amendment)
    aggregate=DurableCallBudget(out/'aggregate.sqlite',experiment_hash=amendment['amendment_hash'],approved=True,**provider.CONFIG)
    first=selected[0];parent=body['parent']
    aggregate.reserve(first['query_id'],first['preflight']['byte_reservation_tokens'])
    aggregate.settle(first['query_id'],parent['input_tokens'],parent['output_tokens'],provider.MODEL)
    generation.write_once(out/'parent-carryover.json',dict(parent_artifact_sha256=PARENT_ARTIFACT_SHA,parent_receipt_sha256=PARENT_RECEIPT_SHA,
        explanation='New authoritative aggregate carries one known settled parent call; original halted journal untouched.',aggregate=aggregate.snapshot()))
    receipts={first['query_id']:dict(parent_receipt,candidate_outcome='candidate_error')};evidence={}
    generation.write_once(out/'parent-receipt.json',receipts[first['query_id']])
    checkpoint()
    contexts={c['query_id']:c for c in baseline['contexts']}
    for index,request in enumerate(selected[1:],start=1):
        qid=request['query_id'];context=contexts[qid]
        _check(request['request_hash'] != parent['request_hash'] and request['request_hash'] == digest(provider.prepare_payload(context)), 'forbidden parent or changed request')
        aggregate.reserve(qid,request['preflight']['byte_reservation_tokens'])
        child_id=digest({'continuation':amendment['amendment_hash'],'original_selected_index':index})
        approval=dict(approved=True,scope='development',experiment_hash=child_id,config=provider.CONFIG,
                      request_hashes=[request['request_hash']],approval_reference=body['approval_reference'])
        child=out/'children'/str(index)
        generation.write_once(out/f'child-{index}-declaration.json',dict(experiment_hash=child_id,request_hash=request['request_hash'],original_selected_index=index))
        try:
            checkpoint() # Persist aggregate reservation before original provider can send.
            receipt=provider.execute_context(context,child,experiment_hash=child_id,approval=approval)
            stem=hashlib.sha256(qid.encode()).hexdigest()
            raw=_read(child/(stem+'.result.raw.json'))['response']
            inputs,outputs,_=_accounting(context,receipt,raw)
            aggregate.settle(qid,inputs,outputs,provider.MODEL)
            outcome=classify_receipt(context,receipt,raw)
            evidence[qid]=_child_evidence(out,index,qid,request['request_hash'],receipt,raw)
            receipts[qid]=dict(receipt,candidate_outcome=outcome)
            generation.write_once(out/f'child-{index}-terminal.json',receipts[qid])
            checkpoint()
        except Exception as exc:
            snapshot=aggregate.snapshot()
            if snapshot['entries'][qid]['status']=='reserved':aggregate.fail(qid,type(exc).__name__)
            else:aggregate.halt()
            result=dict(status='stopped',amendment_hash=amendment['amendment_hash'],failed_query_id=qid,
                        error_type=type(exc).__name__,aggregate=aggregate.snapshot(),evaluation='not_permitted_for_incomplete_batch')
            generation.write_once(out/'status.json',result)
            return result
    records=build_combined_records(baseline,receipts)
    sealed=generation.seal_bundle(baseline['contexts'],dict(rules_plus=baseline['arms']['rules_plus'],llm=records),
                                 baseline['documents'],baseline['dataset_hash'],baseline['label_commitment'])
    generation.write_once(out/'comparison-bundle.json',sealed)
    generation.write_once(out/'public-input-manifest.json',generation.public_input_manifest(sealed))
    generation.write_once(out/'combined-receipts.json',receipts)
    result=dict(status='candidates_sealed',amendment_hash=amendment['amendment_hash'],candidate_seal_hash=sealed['seal_hash'],
                aggregate=aggregate.snapshot(),receipt_evidence=evidence,parent_calls=1,new_calls=6,posthoc_development_amendment=True,evaluation='not_run')
    generation.write_once(out/'status.json',result);checkpoint()
    return result


def verify_completed_run(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path,out):
    """Read-only complete evidence check; never opens label files."""
    provider,_,generation,_,_= _api()
    amendment=verify_amendment(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path)
    body,baseline,selected,parent_receipt=_evidence(original_plan_path,parent_root,parent_artifact_path,baseline_path,amendment['body']['approval_reference'])
    out=Path(out);status=_read(out/'status.json')
    _check(status['status']=='candidates_sealed' and status['amendment_hash']==amendment['amendment_hash']
           and status['parent_calls']==1 and status['new_calls']==6,'complete seven-call amended batch required')
    _check(set(status['receipt_evidence'])=={r['query_id'] for r in selected[1:]},'remaining receipt coverage mismatch')
    contexts={c['query_id']:c for c in baseline['contexts']}
    receipts={selected[0]['query_id']:dict(parent_receipt,candidate_outcome='candidate_error')}
    spent=Decimal(body['parent']['spent_usd'])
    for index,request in enumerate(selected[1:],start=1):
        qid=request['query_id'];stem=hashlib.sha256(qid.encode()).hexdigest()
        receipt=_read(out/'children'/str(index)/(stem+'.result.json'))
        response=_read(out/'children'/str(index)/(stem+'.result.raw.json'))['response']
        evidence=_child_evidence(out,index,qid,request['request_hash'],receipt,response)
        _check(evidence==status['receipt_evidence'][qid],'child evidence hashes changed')
        _,_,cost=_accounting(contexts[qid],receipt,response);spent+=cost
        receipts[qid]=dict(receipt,candidate_outcome=classify_receipt(contexts[qid],receipt,response))
        _check(_read(out/f'child-{index}-terminal.json')==receipts[qid],'terminal outcome changed')
    _check(_read(out/'combined-receipts.json')==receipts and _read(out/'parent-receipt.json')==receipts[selected[0]['query_id']], 'combined or parent receipts changed')
    snapshot=status['aggregate']
    _check(_journal_snapshot(out/'aggregate.sqlite',amendment['amendment_hash'],provider.CONFIG)==snapshot,
           'authoritative aggregate journal differs from status')
    _check(snapshot['calls']==7 and snapshot['halted'] is False and Decimal(snapshot['spent_usd'])==spent
           and spent<=Decimal(provider.CONFIG['usd_limit']) and Decimal(snapshot['reserved_usd'])==0
           and set(snapshot['entries'])==set(receipts), 'aggregate accounting differs')
    for qid,entry in snapshot['entries'].items():
        usage=receipts[qid]['provider_usage']
        _check(entry['status']=='settled' and entry['inputs']==usage['prompt_tokens'] and entry['outputs']==usage['completion_tokens'], 'aggregate entry differs from receipt')
    records=build_combined_records(baseline,receipts)
    reconstructed=generation.seal_bundle(baseline['contexts'],dict(rules_plus=baseline['arms']['rules_plus'],llm=records),
                        baseline['documents'],baseline['dataset_hash'],baseline['label_commitment'])
    saved=_read(out/'comparison-bundle.json')
    _check(saved==reconstructed and status['candidate_seal_hash']==saved['seal_hash'], 'combined candidates changed')
    _check(_read(out/'public-input-manifest.json')==generation.public_input_manifest(saved),'combined input manifest mismatch')
    return amendment,saved,receipts


def evaluate_continuation(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path,run_dir,labels_path,output_path):
    """Separate retrospective development evaluator; all evidence precedes labels."""
    amendment,sealed,receipts=verify_completed_run(amendment_path,original_plan_path,parent_root,parent_artifact_path,baseline_path,run_dir)
    body=sealed['body']
    raw=Path(labels_path).read_bytes()
    _check(hashlib.sha256(raw).hexdigest()==body['label_commitment'],'labels changed after commitment')
    from searchclinic.research.phase2.development import _verified_rows,summarize
    from searchclinic.research.phase2.evaluator import _run_arm,_compare
    from searchclinic.research.phase2.contracts import load_protocol,source_provenance
    from searchclinic.research.phase2.generation import write_once
    from searchclinic.research.costs import MeasuredEngine
    from searchclinic.corpus.evalset import EvalQuery
    from searchclinic.evaluation.metrics import evaluate_all
    rows,contexts,docs=_verified_rows(json.loads(raw),body)
    baseline=evaluate_all(MeasuredEngine(docs),[EvalQuery(r['query'],r['qrels']) for r in rows])
    for row in rows:row['stratum']='healthy' if baseline[row['query']].ndcg>=.8 else 'challenge'
    protocol=load_protocol()
    arms={arm:_run_arm(arm,body['arms'].get(arm),contexts,docs,rows,protocol) for arm in ('no_repair','rules_plus','llm')}
    report=dict(status='posthoc_amended_synthetic_development',evaluation_mode='retrospective_label_assisted_diagnostic',
        posthoc_development_amendment=True,independent_human_review=False,final_test_execution='not_run',
        original_run_status='stopped_after_first_candidate_error',parent_calls=1,new_calls=6,actual_llm_calls=7,
        amendment_hash=amendment['amendment_hash'],candidate_seal_hash=sealed['seal_hash'],
        candidate_error_count=sum(r['candidate_outcome']=='candidate_error' for r in receipts.values()),
        arms=arms,summary={arm:summarize(value) for arm,value in arms.items()},comparison=_compare(arms,protocol,True),
        limitation='Posthoc failure policy amendment after one observed development response; no repaired/retried query, no prospective or final superiority claim.',**source_provenance())
    write_once(output_path,report)
    return report
