"""Reconstruct verdicts from immutable request/raw-response/outcome records.

This checks correspondence and completeness, not provider-signed authenticity.
A saved HTTP transcript is evidence, not a cryptographic attestation from OpenAI.
"""
import json
from pathlib import Path

from .pipeline import freeze, verify
from .transport import _approval, _checked_plan, _parse, _usage


def validate_run(sealed, bundle, *, require_complete=False):
    body = verify(sealed)
    if body.get('version') != 'verified-transport-evidence-v5':
        raise ValueError('unrecognized transport evidence')
    plan = _checked_plan(body['plan'])
    summary = body['summary']
    if plan['bundle'] != bundle or summary.get('input_hash') != bundle['sha256']:
        raise ValueError('transport evidence candidate binding mismatch')
    if (summary.get('plan_hash') != body['plan']['sha256'] or summary.get('model_id') != plan['model_id']
            or summary.get('call_count') != plan['call_count']):
        raise ValueError('transport plan/model/count mismatch')
    kind = summary.get('transport')
    if kind not in ('provider_transport', 'mocked_transport'):
        raise ValueError('unknown transport identity')
    if kind == 'provider_transport':
        _approval(body['plan'], body['approval'])
    n = summary.get('completed_calls')
    if type(n) is not int or not 0 <= n <= plan['call_count'] or len(body['call_records']) != n:
        raise ValueError('transport attempt coverage mismatch')
    if summary.get('unattempted_calls') != plan['call_count']-n:
        raise ValueError('transport missing-call denominator mismatch')
    expected_provider = n if kind == 'provider_transport' else 0
    if summary.get('provider_calls_executed') != expected_provider:
        raise ValueError('provider attempt count mismatch')
    mappings = {(c,r): {record['context']['query_id']:[None]*len(record['candidates'])
                 for record in plan['bundle']['body']['records']}
                for c in plan['conditions'] for r in plan['repeats']}
    valid, unknown, stop_positions = 0, 0, []
    for index, (call, record) in enumerate(zip(plan['calls'], body['call_records'])):
        request = {'plan_hash': body['plan']['sha256'], 'transport': kind, **call}
        if record['request'] != request:
            raise ValueError('request does not match frozen call')
        reservation = record['reservation']
        if (reservation.get('reserved_cost_usd') != plan['per_call_cost_microusd']/1e6
                or reservation.get('cumulative_reserved_cost_usd') != (index+1)*plan['per_call_cost_microusd']/1e6
                or reservation.get('network_attempt_permitted') is not (kind=='provider_transport')):
            raise ValueError('call reservation mismatch')
        raw, outcome = record['raw_response'], record['outcome']
        if (outcome.get('plan_hash') != body['plan']['sha256'] or outcome.get('call_id') != call['call_id']
                or outcome.get('transport') != kind):
            raise ValueError('outcome call identity mismatch')
        if raw.get('body') is None:
            parsed = {'status':'transport_error','verdict':None,'usage':None}
            if raw.get('error') != 'transport_error_details_redacted':
                raise ValueError('missing raw response requires explicit transport error')
        else:
            try:
                payload = json.loads(raw['body'])
            except (TypeError, ValueError):
                payload = None
            if raw.get('http_status') != 200:
                parsed = {'status':'http_error','verdict':None,
                          'usage':_usage(payload) if isinstance(payload,dict) else None}
            else:
                parsed = _parse(payload, call, ('mock:' if kind=='mocked_transport' else '')+plan['model_id'])
        if any(outcome.get(key) != value for key,value in parsed.items()):
            raise ValueError('outcome disconnected from raw response')
        if parsed['usage'] is None:
            unknown += 1
        if parsed['usage'] is None or parsed['status'] in ('http_error','transport_error','api_error'):
            stop_positions.append(index)
        if parsed['verdict'] is not None:
            valid += 1
            mappings[call['condition'],call['repeat']][call['query_id']][call['candidate_index']] = parsed['verdict']
    if summary.get('valid_verdicts') != valid or summary.get('unknown_usage_calls') != unknown:
        raise ValueError('summary contradicts raw outcomes')
    status = summary.get('status')
    if status == 'completed':
        if n != plan['call_count'] or stop_positions:
            raise ValueError('completed summary omits attempts or stopping errors')
    elif status == 'stopped':
        if stop_positions != [n-1] or not n:
            raise ValueError('stopped summary must end at first stopping error')
    else:
        raise ValueError('unsupported run status')
    trials = [dict(condition=c,repeat=r,input_hash=bundle['sha256'],verdicts=mappings[c,r])
              for c in plan['conditions'] for r in plan['repeats']]
    if body['trials'] != trials:
        raise ValueError('exported verdicts disconnected from provider outcomes')
    if require_complete and (kind!='provider_transport' or status!='completed' or n!=plan['call_count']):
        raise ValueError('final requires complete provider evidence')
    return body


def load_run(directory, bundle, *, require_complete=False):
    root = Path(directory)
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))
    plan, summary = read(root/'plan.json'), read(root/'summary.json')
    checked = _checked_plan(plan)
    n = summary.get('completed_calls')
    if type(n) is not int or not 0 <= n <= checked['call_count']:
        raise ValueError('invalid attempt count')
    expected_dirs = {c['call_id'] for c in checked['calls'][:n]}
    if {p.name for p in (root/'calls').iterdir()} != expected_dirs:
        raise ValueError('missing or extra call evidence')
    records = [{key:read(root/'calls'/c['call_id']/filename) for key,filename in
                [('request','request.json'),('reservation','reservation.json'),
                 ('raw_response','raw-response.json'),('outcome','outcome.json')]}
               for c in checked['calls'][:n]]
    trials = [dict(condition=c,repeat=r,input_hash=bundle['sha256'],
                   verdicts=read(root/f'verdicts-{c}-repeat-{r}.json'))
              for c in checked['conditions'] for r in checked['repeats']]
    result = freeze(dict(version='verified-transport-evidence-v5',plan=plan,summary=summary,
        approval=read(root/'approval.json') if summary.get('transport')=='provider_transport' else None,
        call_records=records,trials=trials))
    validate_run(result,bundle,require_complete=require_complete)
    return result
