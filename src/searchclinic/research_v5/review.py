"""Private human-review handoffs and receipts; identities remain self-reported.

This module never calls a model, reads source qrels, or certifies final readiness.
A sealed receipt proves byte binding, not that a person independently reviewed it.
"""
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

from .pipeline import freeze, verify
from .__main__ import write_once

SEM = ('query_id','candidate_index','meaning_preserved','error_type','evidence','ambiguity','reviewer_id','reviewed_at_utc')
REL = ('query_id','doc_id','split','reviewer_id','grade','evidence','ambiguity','reviewed_at_utc')
ERRORS = {'synonym_vs_hierarchy','category_vs_value','target_changed','scope_changed','unsupported_evidence','other'}


def _bytes(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('expected a regular, non-symlink review file')
    if path.stat().st_size > 64*1024*1024:
        raise ValueError('review file exceeds 64 MiB')
    return path.read_bytes()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _csv(data, fields):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    if reader.fieldnames != list(fields):
        raise ValueError('CSV header must match the fixed template exactly')
    rows = list(reader)
    if any(set(row) != set(fields) or any(not isinstance(v,str) for v in row.values()) for row in rows):
        raise ValueError('malformed CSV row')
    return [{k:v.strip() for k,v in row.items()} for row in rows]


def _text(value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('expected nonempty text')
    return value


def _identity(row, kind):
    qid = _text(row['query_id'])
    if kind == 'semantic':
        index = str(row['candidate_index'])
        if not index.isascii() or not index.isdecimal() or str(int(index)) != index:
            raise ValueError('candidate index must be a canonical nonnegative integer')
        return qid, index
    return qid, _text(row['doc_id'])


def _project(inputs, kind):
    if kind == 'semantic':
        projected, identities = [], set()
        for row in inputs:
            key = _identity(row,kind)
            if key in identities:
                raise ValueError('duplicate source candidate')
            identities.add(key)
            context, candidate = row['context'],row['candidate']
            if context['query_id'] != key[0] or candidate['target_query'] != context['query']:
                raise ValueError('source candidate query binding mismatch')
            patch = {'target_query':_text(candidate['target_query'])}
            for group, fields in [('user_words',('form','tag','score')),('synonym_groups',('terms',)),('compound_expansions',('word','parts'))]:
                patch[group] = [{k:item[k] for k in fields if k in item} for item in candidate[group]]
            projected.append({'query_id':key[0],'candidate_index':int(key[1]),'query':_text(context['query']),
                'documents':[{'doc_id':_text(d['doc_id']),'text':_text(d['text'])} for d in context['documents']],
                'candidate':patch})
        return projected, identities
    queries = [{k:q[k] for k in ('query_id','query','split')} for q in inputs['queries']]
    docs = [{k:d[k] for k in ('doc_id','name','description','category','split')} for d in inputs['documents']]
    if len({q['query_id'] for q in queries}) != len(queries) or len({d['doc_id'] for d in docs}) != len(docs):
        raise ValueError('duplicate source query or document')
    for row in [*queries,*docs]:
        if row['split'] not in ('calibration','candidate_final'):
            raise ValueError('unknown source split')
    return {'queries':queries,'documents':docs}, {(q['query_id'],d['doc_id']) for q in queries for d in docs if q['split']==d['split']}


def prepare_handoff(source, kind, output):
    source, output = Path(source), Path(output)
    if kind not in ('semantic','relevance'):
        raise ValueError('unknown review kind')
    manifest_bytes = _bytes(source/'manifest.json')
    manifest = json.loads(manifest_bytes)
    hashes = manifest['files' if kind=='semantic' else 'files_sha256']
    input_name = 'blinded-inputs.json' if kind=='semantic' else 'inputs.json'
    names = [input_name,*[f'reviewer-{r}.csv' if kind=='semantic' else f'review/reviewer-{r}-pairs.csv' for r in ('a','b')]]
    files = {name:_bytes(source/name) for name in names}
    if any(_hash(data) != hashes[name] for name,data in files.items()):
        raise ValueError('source manifest hash mismatch')
    projected, expected = _project(json.loads(files[input_name]),kind)
    if not expected:
        raise ValueError('empty review population')
    fields = SEM if kind=='semantic' else REL
    templates = [_csv(files[name],fields) for name in names[1:]]
    identities = ('query_id','candidate_index') if kind=='semantic' else ('query_id','doc_id','split')
    for rows in templates:
        keys = [_identity(row,kind) for row in rows]
        if len(keys)!=len(set(keys)) or set(keys)!=expected:
            raise ValueError('source template coverage mismatch')
        if any(row[k] for row in rows for k in fields if k not in identities):
            raise ValueError('source templates must be blank, not completed reviews')
        if kind=='relevance':
            splits={q['query_id']:q['split'] for q in projected['queries']}
            if any(row['split']!=splits[row['query_id']] for row in rows):
                raise ValueError('source template split mismatch')
    content_hash = freeze(projected)['sha256']
    study_hash = freeze({'kind':kind,'inputs':content_hash,'source_manifest':_hash(manifest_bytes),
                         'identities':sorted(expected)})['sha256']
    output.mkdir(parents=True,exist_ok=False)
    for role, rows in zip(('a','b'),templates):
        folder = output/f'reviewer-{role}';folder.mkdir()
        write_once(folder/'inputs.json',projected)
        for filename in ('template.csv','submission.csv'):
            with (folder/filename).open('x',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        write_once(folder/'packet.json',freeze({'version':'review-packet-v5','kind':kind,'role':role,
            'study_hash':study_hash,'source_manifest_sha256':_hash(manifest_bytes),
            'inputs_hash':content_hash,'expected_count':len(expected),
            'files':{name:_hash(_bytes(folder/name)) for name in ('inputs.json','template.csv')}}))
        instructions = ('독립 검수 전달물 — 실제 판정 전 빈 양식입니다.\n\n'
            'inputs.json의 질의·원문·수정 내용을 읽고 submission.csv만 작성하세요. template.csv와 packet.json은 변경하지 마세요.\n'
            '다른 판정자의 파일, LLM 판정/confidence, 검색 결과·정답·원본 QA 답안을 보지 마세요. 외부 정답 검색도 하지 마세요.\n'
            'reviewer_id는 실제 담당자에게 배정된 별칭, reviewed_at_utc는 실제 판정 시각(UTC ISO8601, 예: 2026-10-31T13:00:00Z)을 입력하세요.\n'
            'evidence에 원문 인용과 판단 이유를 쓰세요. 판단 불가는 값을 비우고 ambiguity에 이유를 씁니다. 빈칸은 0/false가 아닙니다.\n'
            '의미 검수: meaning_preserved=true/false; 모든 수정이 대상과 범위를 보존해야 true입니다. false이면 error_type에 지침의 오류 유형을 씁니다.\n'
            'error_type: synonym_vs_hierarchy; category_vs_value; target_changed; scope_changed; unsupported_evidence; other. 복수는 세미콜론으로 구분합니다.\n'
            '같은 문서에 두 표현이 있다는 사실은 동의 관계의 증명이 아닙니다. 범주와 특정 값, 상하위 개념, 질문 대상을 구별하세요.\n'
            '관련성 검수: grade=0(도움 없음)/1(부분 근거)/2(직접 답 근거). 검색 순위로 판정하지 마세요.\n'
            '이름 대신 별칭을 사용하세요. 제출본과 독립성에 관한 본인 확인은 관리자가 보존합니다. CSV만으로 사람 신원/독립성을 증명할 수 없습니다.\n'
            '검수표와 원문은 비공개로 전달하며 공개 저장소/이슈에 올리지 마세요. 두 최초 판정 뒤 불일치는 제3자가 조정합니다.\n')
        if kind=='relevance':
            instructions += '\n원문 출처: KLUE MRC v1.1, https://github.com/KLUE-benchmark/KLUE, CC-BY-SA-4.0. 원문은 공개 원천에서 발췌됐지만 이 검수 배치의 상세 공개는 보류합니다.\n'
        with (folder/'INSTRUCTIONS.txt').open('x',encoding='utf-8') as stream:stream.write(instructions)
        with zipfile.ZipFile(output/f'reviewer-{role}.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.iterdir()):archive.write(path,path.name)
    summary={'kind':kind,'study_hash':study_hash,'items_per_reviewer':len(expected),'reviewers_assigned':False,
             'human_reviews_completed':0,'provider_calls_executed':0,'final_evaluation_ready':False}
    write_once(output/'summary.json',summary)
    return summary


def _commitment(packet, identities):
    return freeze({'kind':packet['kind'],'inputs':packet['inputs_hash'],
                   'source_manifest':packet['source_manifest_sha256'],'identities':sorted(identities)})['sha256']


def _packet_metadata(sealed):
    packet=verify(sealed)
    fields={'version','kind','role','study_hash','source_manifest_sha256','inputs_hash','expected_count','files'}
    if (set(packet)!=fields or packet['version']!='review-packet-v5' or packet['kind'] not in ('semantic','relevance')
            or packet['role'] not in ('a','b') or type(packet['expected_count']) is not int or packet['expected_count']<1
            or set(packet['files'])!={'inputs.json','template.csv'}):
        raise ValueError('invalid review packet schema')
    for digest in [packet['study_hash'],packet['inputs_hash'],packet['source_manifest_sha256'],*packet['files'].values()]:
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid packet hash')
    return packet


def _packet(folder):
    folder=Path(folder)
    packet=_packet_metadata(json.loads(_bytes(folder/'packet.json')))
    for name,digest in packet['files'].items():
        if _hash(_bytes(folder/name))!=digest:raise ValueError('immutable packet file hash mismatch')
    inputs=json.loads(_bytes(folder/'inputs.json'))
    if freeze(inputs)['sha256']!=packet['inputs_hash']:raise ValueError('input content hash mismatch')
    if packet['kind']=='semantic':
        source=[{'query_id':r['query_id'],'candidate_index':r['candidate_index'],
                 'context':{'query_id':r['query_id'],'query':r['query'],'documents':r['documents']},
                 'candidate':r['candidate']} for r in inputs]
        projected,population=_project(source,'semantic')
    else:
        projected,population=_project(inputs,'relevance')
    if projected!=inputs:raise ValueError('review inputs contain unexpected fields')
    fields=SEM if packet['kind']=='semantic' else REL
    rows=_csv(_bytes(folder/'template.csv'),fields)
    expected={_identity(row,packet['kind']):row for row in rows}
    if len(rows)!=len(expected) or set(expected)!=population or len(expected)!=packet['expected_count']:
        raise ValueError('packet template coverage mismatch')
    identities=('query_id','candidate_index') if packet['kind']=='semantic' else ('query_id','doc_id','split')
    if any(row[k] for row in rows for k in fields if k not in identities):
        raise ValueError('packet template is not blank')
    if packet['kind']=='relevance':
        splits={q['query_id']:q['split'] for q in inputs['queries']}
        if any(r['split']!=splits[r['query_id']] for r in rows):raise ValueError('packet split mismatch')
    if _commitment(packet,population)!=packet['study_hash']:raise ValueError('study commitment mismatch')
    return packet,fields,expected


def _utc(text):
    try: stamp=datetime.fromisoformat(text.replace('Z','+00:00'))
    except (ValueError,TypeError): raise ValueError('review timestamp must be ISO8601 UTC') from None
    if stamp.tzinfo is None or stamp.utcoffset()!=timezone.utc.utcoffset(stamp):
        raise ValueError('review timestamp must be ISO8601 UTC')


def _judgment(row, kind, reviewer_id):
    value_field='meaning_preserved' if kind=='semantic' else 'grade'
    allowed={'false':0,'true':1} if kind=='semantic' else {'0':0,'1':1,'2':2}
    value,ambiguity=row[value_field],row['ambiguity']
    if kind=='semantic':value=value.casefold()
    if value and value not in allowed:raise ValueError('invalid review value')
    if value and ambiguity:raise ValueError('a definite grade cannot also be ambiguous')
    if row['reviewer_id'] and row['reviewer_id'].strip().casefold()!=reviewer_id:raise ValueError('reviewer identity mismatch')
    if row['reviewed_at_utc']:_utc(row['reviewed_at_utc'])
    state='graded' if value else 'ambiguous' if ambiguity else 'missing'
    if state!='missing':
        if row['reviewer_id'].strip().casefold()!=reviewer_id:raise ValueError('reviewer identity required')
        _utc(row['reviewed_at_utc'])
    if value:
        _text(row['evidence'])
        if kind=='semantic':
            errors=set(row['error_type'].split(';')) if row['error_type'] else set()
            if errors-ERRORS or (value=='false' and not errors):raise ValueError('semantic error type required/invalid')
    return state, allowed.get(value)


def validate_submission(packet_dir, submission, reviewer_id):
    reviewer_id=_text(reviewer_id).strip().casefold()
    packet,fields,expected=_packet(packet_dir)
    data=_bytes(submission);submitted=_csv(data,fields);seen=set();rows=[]
    for row in submitted:
        key=_identity(row,packet['kind'])
        if key in seen or key not in expected:raise ValueError('duplicate or foreign review identity')
        seen.add(key)
        if packet['kind']=='relevance' and row['split']!=expected[key]['split']:raise ValueError('review split mismatch')
        state,value=_judgment(row,packet['kind'],reviewer_id)
        rows.append({'identity':list(key),'status':state,'value':value,'record':row})
    for key in expected.keys()-seen:
        rows.append({'identity':list(key),'status':'missing','value':None,'record':None})
    rows.sort(key=lambda row:row['identity'])
    counts=Counter(row['status'] for row in rows)
    return freeze({'version':'human-review-submission-v5','kind':packet['kind'],'role':packet['role'],
        'study_hash':packet['study_hash'],'packet_hash':json.loads(_bytes(Path(packet_dir)/'packet.json'))['sha256'],
        'packet':json.loads(_bytes(Path(packet_dir)/'packet.json')),
        'submission_sha256':_hash(data),'reviewer_id':reviewer_id,
        'identity_status':'self_reported_not_independently_authenticated',
        'counts':{'expected':len(expected),**{k:counts[k] for k in ('graded','ambiguous','missing')}},
        'rows':rows,'final_evaluation_ready':False})


def _validated_receipt(sealed):
    body=verify(sealed)
    fields={'version','kind','role','study_hash','packet_hash','packet','submission_sha256','reviewer_id',
            'identity_status','counts','rows','final_evaluation_ready'}
    if set(body)!=fields or body['version']!='human-review-submission-v5':
        raise ValueError('expected complete human review receipt schema')
    packet=_packet_metadata(body['packet'])
    if (body['packet_hash']!=body['packet']['sha256'] or body['kind']!=packet['kind']
            or body['role']!=packet['role'] or body['study_hash']!=packet['study_hash']):
        raise ValueError('receipt packet provenance mismatch')
    digest=body['submission_sha256']
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('missing or invalid submission hash')
    if (body['reviewer_id']!=_text(body['reviewer_id']).strip().casefold()
            or body['final_evaluation_ready'] is not False):
        raise ValueError('invalid reviewer/readiness metadata')
    rows={};counts=Counter()
    for row in body['rows']:
        key=tuple(row['identity'])
        if len(key)!=2 or key in rows:raise ValueError('invalid/duplicate receipt identity')
        record=row['record']
        if record is None:
            state,value='missing',None
        else:
            fields=SEM if body['kind']=='semantic' else REL
            if set(record)!=set(fields) or _identity(record,body['kind'])!=key:
                raise ValueError('receipt identity mismatch')
            state,value=_judgment(record,body['kind'],body['reviewer_id'])
        if row['status']!=state or type(row['value']) is not type(value) or row['value']!=value:
            raise ValueError('receipt value disagrees with submitted record')
        rows[key]=row;counts[state]+=1
    expected={'expected':len(rows),**{k:counts[k] for k in ('graded','ambiguous','missing')}}
    if (not rows or body['counts']!=expected or len(rows)!=packet['expected_count']
            or _commitment(packet,rows)!=packet['study_hash']):
        raise ValueError('receipt coverage/count/study mismatch')
    return body,rows


def _agreement(a,b,kind):
    pairs=[(a[k]['value'],b[k]['value']) for k in a if a[k]['status']==b[k]['status']=='graded']
    n=len(pairs);levels=2 if kind=='semantic' else 3
    result={'paired_graded':n,'total_items':len(a),'weighting':'unweighted' if levels==2 else 'quadratic',
            'observed_agreement':None,'kappa':None,'kappa_status':'no_paired_definite_judgments'}
    if not n:return result
    left,right=Counter(x for x,_ in pairs),Counter(y for _,y in pairs)
    distance=lambda x,y: (x-y)**2/(levels-1)**2
    observed=sum(distance(x,y) for x,y in pairs)/n
    expected=sum(left[x]*right[y]*distance(x,y) for x in range(levels) for y in range(levels))/n**2
    result['observed_agreement']=sum(x==y for x,y in pairs)/n
    result['kappa_status']='defined' if expected else 'undefined_constant_marginals'
    result['kappa']=1-observed/expected if expected else None
    return result


def reconcile(review_a, review_b, adjudications=None):
    a,arows=_validated_receipt(review_a);b,brows=_validated_receipt(review_b)
    if a['kind']!=b['kind'] or a['study_hash']!=b['study_hash'] or set(arows)!=set(brows):
        raise ValueError('review study/coverage mismatch')
    if (a['role'],b['role'])!=('a','b') or a['reviewer_id']==b['reviewer_id']:
        raise ValueError('two different reviewers and roles required')
    values,queue={},{}
    for key in arows:
        x,y=arows[key],brows[key]
        if 'missing' in (x['status'],y['status']):reason='missing_initial_review'
        elif 'ambiguous' in (x['status'],y['status']):reason='ambiguous'
        elif x['value']!=y['value']:reason='disagreement'
        else:
            values[key]=x['value'];continue
        queue[key]={'identity':list(key),'reason':reason,'reviewer_a_value':x['value'],
                    'reviewer_b_value':y['value'],'resolved':False}
    id_fields=('query_id','candidate_index') if a['kind']=='semantic' else ('query_id','doc_id')
    allowed={'true':1,'false':0} if a['kind']=='semantic' else {'0':0,'1':1,'2':2}
    fields={*id_fields,'final_value','adjudicator_id','decision_reason','adjudicated_at_utc'}
    seen=set();audit=[]
    for row in adjudications or []:
        if set(row)!=fields or any(not isinstance(v,str) for v in row.values()):
            raise ValueError('invalid adjudication schema')
        key=_identity(row,a['kind'])
        if key not in arows or key in seen:raise ValueError('foreign or duplicate adjudication identity')
        seen.add(key)
        if not any(row[k].strip() for k in ('final_value','adjudicator_id','decision_reason','adjudicated_at_utc')):
            if key not in queue:raise ValueError('blank adjudication must reference the pending queue')
            continue
        if key not in queue or queue[key]['reason']=='missing_initial_review':
            raise ValueError('only existing disagreement/ambiguity may be adjudicated once')
        adjudicator=_text(row['adjudicator_id']).strip().casefold()
        if adjudicator in (a['reviewer_id'],b['reviewer_id']):raise ValueError('distinct adjudicator required')
        _text(row['decision_reason']);_utc(row['adjudicated_at_utc'])
        if row['final_value'] not in allowed:raise ValueError('explicit valid adjudicated value required')
        values[key]=allowed[row['final_value']];queue[key]['resolved']=True;audit.append(dict(row))
    pending=len(arows)-len(values)
    labels=None
    if not pending:
        labels={}
        for (qid,item),value in sorted(values.items()):
            labels.setdefault(qid,{})[item]=bool(value) if a['kind']=='semantic' else value
    return freeze({'version':'human-review-reconciliation-v5','kind':a['kind'],'study_hash':a['study_hash'],
        'review_hashes':[review_a['sha256'],review_b['sha256']],
        'reviewer_ids':[a['reviewer_id'],b['reviewer_id']],
        'identity_status':'self_reported_not_independently_authenticated',
        'agreement':_agreement(arows,brows,a['kind']),'queue':list(queue.values()),'adjudications':audit,
        'pending_count':pending,'resolved_count':len(values),'labels_complete':not pending,'labels':labels,
        'final_evaluation_ready':False,
        'remaining_gates':['actual_reviewer_independence_attestation','query_eligibility_and_concept_review',
                           'complete_historical_exposure_audit','frozen_final_protocol_and_candidates']})



def load_submission_receipt(path):
    """CLI boundary: rederive the receipt from its preserved packet and raw bytes."""
    path=Path(path)
    sealed=json.loads(_bytes(path))
    body,_=_validated_receipt(sealed)
    derived=validate_submission(path.parent/'packet',path.parent/'original-submission.csv',body['reviewer_id'])
    if derived!=sealed:raise ValueError('archived originals disagree with review receipt')
    return sealed
