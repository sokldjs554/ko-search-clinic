"""Synthetic fixtures exercise intake; they are never human research evidence."""
import csv
import hashlib
import importlib
import json
from pathlib import Path

import pytest

SEM = ['query_id','candidate_index','meaning_preserved','error_type','evidence','ambiguity','reviewer_id','reviewed_at_utc']
REL = ['query_id','doc_id','split','reviewer_id','grade','evidence','ambiguity','reviewed_at_utc']


def api():
    return importlib.import_module('searchclinic.research_v5.review')


def put_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def put_csv(path, fields, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=fields);w.writeheader();w.writerows(rows)


def source(tmp_path, kind='semantic'):
    root=tmp_path/'source';root.mkdir()
    if kind=='semantic':
        inputs=[{'query_id':q,'candidate_index':0,'context':{'query_id':q,'query':'표현',
            'search_total':999,'observation':{'confidence':'DO_NOT_SHARE'},
            'documents':[{'doc_id':'d','text':'표현과 원문','tokens':['DO_NOT_SHARE']}]},
            'candidate':{'target_query':'표현','reasoning':'DO_NOT_SHARE','diagnosis_family':'DO_NOT_SHARE',
                'synonym_groups':[{'terms':['표현','원문']}],'user_words':[],'compound_expansions':[]}}
            for q in ('q1','q2')]
        put_json(root/'blinded-inputs.json',inputs)
        rows=[dict.fromkeys(SEM,'')|{'query_id':q,'candidate_index':'0'} for q in ('q1','q2')]
        for role in ('a','b'):put_csv(root/f'reviewer-{role}.csv',SEM,list(reversed(rows)) if role=='b' else rows)
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        put_json(root/'manifest.json',{'files':files,'source_bundle_hash':'a'*64})
    else:
        put_json(root/'inputs.json',{'queries':[{'query_id':'q1','query':'질문','split':'calibration'}],
            'documents':[{'doc_id':d,'name':'문서','description':'원문','category':'분류','split':'calibration'} for d in ('d1','d2','d3')]})
        rows=[dict.fromkeys(REL,'')|{'query_id':'q1','doc_id':d,'split':'calibration'} for d in ('d1','d2','d3')]
        for role in ('a','b'):put_csv(root/'review'/f'reviewer-{role}-pairs.csv',REL,rows)
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        put_json(root/'manifest.json',{'files_sha256':files})
    (root/'private').mkdir();put_json(root/'private/source-proxy-labels.json',{'SECRET_GOLD':'DO_NOT_SHARE'})
    return root


def prepared(tmp_path,kind='semantic'):
    root=source(tmp_path,kind);out=tmp_path/'packets'
    api().prepare_handoff(root,kind,out)
    return out


def submit(packet, reviewer, values, *, ambiguous=()):
    with (packet/'template.csv').open(encoding='utf-8-sig',newline='') as s:
        reader=csv.DictReader(s);fields=reader.fieldnames;rows=list(reader)
    value_field='meaning_preserved' if 'meaning_preserved' in fields else 'grade'
    rows.sort(key=lambda r:(r['query_id'],r.get('candidate_index',r.get('doc_id'))))
    for i,row in enumerate(rows):
        row.update(reviewer_id=reviewer,reviewed_at_utc='2026-10-31T13:00:00Z')
        if i in ambiguous:row['ambiguity']='원문만으로 판단 불가'
        elif values[i] is not None:
            row.update({value_field:values[i],'evidence':'원문 근거를 읽고 판정함'})
            if value_field=='meaning_preserved' and values[i]=='false':row['error_type']='scope_changed'
    path=packet/f'{reviewer}.csv';put_csv(path,fields,rows)
    return path


def test_handoff_excludes_retrieval_signals_generator_rationale_and_private_labels(tmp_path):
    root=source(tmp_path);before={p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    out=tmp_path/'packets';api().prepare_handoff(root,'semantic',out)
    content=(out/'reviewer-a/inputs.json').read_text(encoding='utf-8')
    assert 'DO_NOT_SHARE' not in content and 'search_total' not in content and 'reasoning' not in content
    assert '표현과 원문' in content
    assert not list(out.rglob('*labels*')) and all(p.read_bytes()==v for p,v in before.items())
    a=api().validate_submission(out/'reviewer-a',out/'reviewer-a/submission.csv','person-a')
    assert a['body']['counts']=={'expected':2,'graded':0,'ambiguous':0,'missing':2}
    assert a['body']['final_evaluation_ready'] is False
    with pytest.raises(FileExistsError):api().prepare_handoff(root,'semantic',out)


def test_false_is_a_judgment_and_blanks_are_missing(tmp_path):
    out=prepared(tmp_path);folder=out/'reviewer-a'
    result=api().validate_submission(folder,submit(folder,'r1',['false',None]),'r1')['body']
    assert result['counts']=={'expected':2,'graded':1,'ambiguous':0,'missing':1}
    assert result['rows'][0]['value']==0 and result['rows'][1]['value'] is None


@pytest.mark.parametrize('change',['duplicate','unknown','grade','identity','timestamp','evidence','extra_column'])
def test_bad_submissions_fail_instead_of_silently_becoming_labels(tmp_path,change):
    out=prepared(tmp_path);folder=out/'reviewer-a';path=submit(folder,'r1',['true','false'])
    with path.open(encoding='utf-8-sig',newline='') as s:r=csv.DictReader(s);fields=r.fieldnames;rows=list(r)
    if change=='duplicate':rows.append(rows[0])
    elif change=='unknown':rows[0]['query_id']='not-in-packet'
    elif change=='grade':rows[0]['meaning_preserved']='1'
    elif change=='identity':rows[0]['reviewer_id']='someone-else'
    elif change=='timestamp':rows[0]['reviewed_at_utc']='2026-10-31T13:00:00'
    elif change=='evidence':rows[0]['evidence']=''
    else:fields=[*fields,'extra'];rows[0]['extra']='hidden'
    put_csv(path,fields,rows)
    with pytest.raises(ValueError):api().validate_submission(folder,path,'r1')


def test_changed_immutable_input_and_source_hash_fail(tmp_path):
    out=prepared(tmp_path);folder=out/'reviewer-a'
    (folder/'inputs.json').write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError,match='hash'):api().validate_submission(folder,folder/'submission.csv','r1')


def test_relevance_zero_and_ambiguity_are_distinct_and_wrong_split_fails(tmp_path):
    out=prepared(tmp_path,'relevance');folder=out/'reviewer-a';path=submit(folder,'r1',['0',None,None],ambiguous=(1,))
    result=api().validate_submission(folder,path,'r1')['body']
    assert result['counts']=={'expected':3,'graded':1,'ambiguous':1,'missing':1}
    with path.open(encoding='utf-8-sig',newline='') as s:r=csv.DictReader(s);fields=r.fieldnames;rows=list(r)
    rows[0]['split']='candidate_final';put_csv(path,fields,rows)
    with pytest.raises(ValueError):api().validate_submission(folder,path,'r1')


def reviewed_pair(tmp_path,values_a,values_b,kind='semantic',ambiguous_a=()):
    out=prepared(tmp_path,kind)
    a=api().validate_submission(out/'reviewer-a',submit(out/'reviewer-a','r1',values_a,ambiguous=ambiguous_a),'r1')
    b=api().validate_submission(out/'reviewer-b',submit(out/'reviewer-b','r2',values_b),'r2')
    return a,b


def test_disagreement_requires_distinct_adjudicator_and_keeps_first_judgments(tmp_path):
    a,b=reviewed_pair(tmp_path,['true','false'],['true','true'])
    report=api().reconcile(a,b)['body']
    assert report['agreement']['observed_agreement']==.5
    assert report['agreement']['kappa']==0
    assert report['labels'] is None and report['pending_count']==1
    row={'query_id':'q2','candidate_index':'0','final_value':'false','adjudicator_id':'r3',
         'decision_reason':'독립 조정 근거','adjudicated_at_utc':'2026-10-31T14:00:00Z'}
    resolved=api().reconcile(a,b,[row])['body']
    assert resolved['labels']=={'q1':{'0':True},'q2':{'0':False}}
    assert resolved['final_evaluation_ready'] is False
    assert resolved['review_hashes']==[a['sha256'],b['sha256']]
    row['adjudicator_id']='r1'
    with pytest.raises(ValueError):api().reconcile(a,b,[row])


def test_missing_review_cannot_be_filled_by_adjudicator_and_ambiguity_is_explicit(tmp_path):
    a,b=reviewed_pair(tmp_path,[None,None],['true','true'],ambiguous_a=(0,))
    report=api().reconcile(a,b)['body']
    assert report['pending_count']==2 and report['labels'] is None
    assert {r['reason'] for r in report['queue']}=={'ambiguous','missing_initial_review'}
    row={'query_id':'q2','candidate_index':'0','final_value':'true','adjudicator_id':'r3',
         'decision_reason':'cannot substitute first reviewer','adjudicated_at_utc':'2026-10-31T14:00:00Z'}
    with pytest.raises(ValueError):api().reconcile(a,b,[row])


def test_relevance_quadratic_kappa_and_constant_grade_denominator(tmp_path):
    a,b=reviewed_pair(tmp_path,['0','1','2'],['0','2','2'],kind='relevance')
    r=api().reconcile(a,b)['body']
    assert r['agreement']['paired_graded']==3
    assert r['agreement']['observed_agreement']==pytest.approx(2/3)
    assert r['agreement']['kappa']==pytest.approx(.8)
    assert r['agreement']['weighting']=='quadratic'


def test_same_reviewer_wrong_study_and_agreement_override_fail(tmp_path):
    from searchclinic.research_v5.pipeline import freeze
    a,b=reviewed_pair(tmp_path,['true','true'],['true','true'])
    r=api().reconcile(a,b)['body']
    assert r['agreement']['kappa'] is None and r['agreement']['kappa_status']=='undefined_constant_marginals'
    assert r['labels']=={'q1':{'0':True},'q2':{'0':True}}
    for field,value in [('reviewer_id','r1'),('study_hash','different'),('role','a')]:
        changed=json.loads(json.dumps(b['body']));changed[field]=value
        with pytest.raises(ValueError):api().reconcile(a,freeze(changed))
    override={'query_id':'q1','candidate_index':'0','final_value':'false','adjudicator_id':'r3',
         'decision_reason':'not allowed to override agreement','adjudicated_at_utc':'2026-10-31T14:00:00Z'}
    with pytest.raises(ValueError):api().reconcile(a,b,[override])


def test_sealed_submission_with_edited_value_cannot_disagree_with_original_record(tmp_path):
    from searchclinic.research_v5.pipeline import freeze
    a,b=reviewed_pair(tmp_path,['true','false'],['true','false'])
    a['body']['rows'][0]['value']=0
    with pytest.raises(ValueError):api().reconcile(freeze(a['body']),b)


def test_cli_keeps_original_bytes_and_rejects_public_output(tmp_path):
    import subprocess
    import sys
    from searchclinic.research_v5 import transport
    root=Path(__file__).resolve().parents[1]
    # Use a real ignored work path to exercise the CLI publication boundary.
    import tempfile
    transport.WORK_ROOT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-test-',dir=transport.WORK_ROOT) as local:
        folder=Path(local);out=prepared(folder)
        packet=out/'reviewer-a';output=folder/'validated'
        command=[sys.executable,str(root/'scripts/review_v5.py'),'validate','--packet',str(packet),
            '--submission',str(packet/'submission.csv'),'--reviewer-id','unassigned-a','--out',str(output)]
        run=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        assert run.returncode==0,run.stderr
        assert (output/'original-submission.csv').read_bytes()==(packet/'submission.csv').read_bytes()
        assert json.loads((output/'summary.json').read_text(encoding='utf-8'))['graded']==0
        assert not (output/'private/labels.json').exists()
        second=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        assert second.returncode!=0 and 'already exists' in second.stderr
        command[-1]=str(tmp_path/'outside-work')
        blocked=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        assert blocked.returncode!=0 and not (tmp_path/'outside-work').exists()


def test_partial_adjudication_sheet_keeps_unfilled_rows_pending(tmp_path):
    a,b=reviewed_pair(tmp_path,['false','false'],['true','true'])
    rows=[{'query_id':'q1','candidate_index':'0','final_value':'false','adjudicator_id':'r3',
           'decision_reason':'원문 범위 조정','adjudicated_at_utc':'2026-10-31T14:00:00Z'},
          {'query_id':'q2','candidate_index':'0','final_value':'','adjudicator_id':'',
           'decision_reason':'','adjudicated_at_utc':''}]
    r=api().reconcile(a,b,rows)['body']
    assert r['pending_count']==1 and r['labels'] is None and r['resolved_count']==1


def test_spreadsheet_boolean_case_and_reviewer_alias_whitespace_are_not_loopholes(tmp_path):
    out=prepared(tmp_path)
    folder=out/'reviewer-a';path=submit(folder,'R1',['TRUE','FALSE'])
    # A false judgment still needs a semantic error type when Excel uppercases it.
    with path.open(encoding='utf-8-sig',newline='') as s:r=csv.DictReader(s);fields=r.fieldnames;rows=list(r)
    rows[1]['error_type']='scope_changed';put_csv(path,fields,rows)
    a=api().validate_submission(folder,path,'r1')
    b=api().validate_submission(out/'reviewer-b',submit(out/'reviewer-b','r2',['false','true']),'r2')
    row={'query_id':'q1','candidate_index':'0','final_value':'true','adjudicator_id':' R1 ',
         'decision_reason':'same person cannot adjudicate','adjudicated_at_utc':'2026-10-31T14:00:00Z'}
    with pytest.raises(ValueError):api().reconcile(a,b,[row])


def test_packet_reseal_cannot_hide_changed_question_or_population(tmp_path):
    from searchclinic.research_v5.pipeline import freeze
    out=prepared(tmp_path);folder=out/'reviewer-a'
    inputs=json.loads((folder/'inputs.json').read_text(encoding='utf-8'));inputs[0]['query']='다른 질문'
    put_json(folder/'inputs.json',inputs)
    packet=json.loads((folder/'packet.json').read_text(encoding='utf-8'))
    packet['body']['files']['inputs.json']=hashlib.sha256((folder/'inputs.json').read_bytes()).hexdigest()
    put_json(folder/'packet.json',freeze(packet['body']))
    with pytest.raises(ValueError):api().validate_submission(folder,folder/'submission.csv','r1')


def test_truncated_receipts_and_missing_provenance_cannot_become_complete(tmp_path):
    from searchclinic.research_v5.pipeline import freeze
    a,b=reviewed_pair(tmp_path,['true',None],['true',None])
    originals=json.loads(json.dumps([a,b]))
    for r in (a,b):
        r['body']['rows']=r['body']['rows'][:1]
        r['body']['counts']={'expected':1,'graded':1,'missing':0,'ambiguous':0}
    with pytest.raises(ValueError):api().reconcile(freeze(a['body']),freeze(b['body']))
    for field in ('submission_sha256','packet_hash'):
        left,right=json.loads(json.dumps(originals))
        del left['body'][field]
        with pytest.raises(ValueError,match='schema'):api().reconcile(freeze(left['body']),right)


def test_duplicate_blank_or_blank_and_filled_adjudication_is_rejected(tmp_path):
    a,b=reviewed_pair(tmp_path,['true','false'],['false','true'])
    blank={'query_id':'q1','candidate_index':'0','final_value':'','adjudicator_id':'',
           'decision_reason':'','adjudicated_at_utc':''}
    filled={**blank,'final_value':'true','adjudicator_id':'r3','decision_reason':'원문',
            'adjudicated_at_utc':'2026-10-31T14:00:00Z'}
    for rows in ([blank,blank],[blank,filled],[filled,blank]):
        with pytest.raises(ValueError):api().reconcile(a,b,rows)


def test_cli_rechecks_original_submissions_and_archives_adjudication_bytes(tmp_path):
    import subprocess
    import sys
    import tempfile
    from searchclinic.research_v5 import transport
    root=Path(__file__).resolve().parents[1]
    transport.WORK_ROOT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-archive-test-',dir=transport.WORK_ROOT) as local:
        folder=Path(local);packets=prepared(folder)
        def run(*args):
            return subprocess.run([sys.executable,str(root/'scripts/review_v5.py'),*map(str,args)],
                capture_output=True,text=True,encoding='utf-8')
        for role,person,values in [('a','r1',['true','false']),('b','r2',['true','true'])]:
            packet=packets/f'reviewer-{role}'
            submit_path=submit(packet,person,values)
            r=run('validate','--packet',packet,'--submission',submit_path,'--reviewer-id',person,'--out',folder/role)
            assert r.returncode==0,r.stderr
        fields=['query_id','candidate_index','final_value','adjudicator_id','decision_reason','adjudicated_at_utc']
        adjudication=folder/'adjudication.csv'
        put_csv(adjudication,fields,[{'query_id':'q2','candidate_index':'0','final_value':'false','adjudicator_id':'r3',
            'decision_reason':'  원문 근거를 보존  ','adjudicated_at_utc':'2026-10-31T14:00:00Z'}])
        r=run('reconcile','--review-a',folder/'a/receipt.json','--review-b',folder/'b/receipt.json',
            '--adjudications',adjudication,'--out',folder/'reconciled')
        assert r.returncode==0,r.stderr
        assert (folder/'reconciled/original-adjudication.csv').read_bytes()==adjudication.read_bytes()
        body=json.loads((folder/'reconciled/receipt.json').read_text(encoding='utf-8'))['body']
        assert body['adjudication_source']['sha256']==hashlib.sha256(adjudication.read_bytes()).hexdigest()
        assert body['adjudication_source']['received_at_utc'].endswith('+00:00')
        # Altering archived raw bytes must block a subsequent reconciliation.
        with (folder/'a/original-submission.csv').open(mode='ab') as stream:stream.write(b'\n')
        broken=run('reconcile','--review-a',folder/'a/receipt.json','--review-b',folder/'b/receipt.json','--out',folder/'blocked')
        assert broken.returncode!=0 and not (folder/'blocked').exists()
