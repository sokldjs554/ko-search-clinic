"""Pinned public MIRACL acquisition; final artifact encrypted, no LLM or scoring.
Only generic source/metadata are publishable. Never upload working directory.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile

SELECTED_SHA256='62b0a870c0476b38c76e4a176a4aee73dd66e8fcffd72b062bef9c2497e2b608'
EXPECTED_CANONICAL_SHA256='b59b563066b0fd95fd684e37499d57affc2f6bb8c818fb0a680ac592b7466281'
PUBLIC_KEY=bytes.fromhex('63a13244cf1c055e3da4f3ba1a5472ee872b74bf3df7cb2a3148a644f4183161')
CONTEXT=b'miracl-restore-v1'
MANIFEST={'corpus_revision': 'd921ec7e349ce0d28daf30b2da9da5ee698bef0d', 'files': {'MIRACL_CORPUS_CARD.md': {'sha256': 'e8779ef1087590dae1d74396ca575e792f3fd1a3bcf2aa3caf6b2733c4f41bad', 'url': 'https://huggingface.co/datasets/miracl/miracl-corpus/raw/d921ec7e349ce0d28daf30b2da9da5ee698bef0d/README.md'}, 'MIRACL_DATA_CARD.md': {'sha256': '218fdac67872c9732e8b35416c650582837c27923a7e579ab2d4f446a3199218', 'url': 'https://huggingface.co/datasets/miracl/miracl/raw/5be20db9509754dadad47689368639fcec739c00/README.md'}, 'qrels.miracl-v1.0-ko-dev.tsv': {'sha256': '88827ccc5b64e531b25f70eef30202d33daa9bfa3ac8cceadf5cdbd5ca5034df', 'url': 'https://huggingface.co/datasets/miracl/miracl/resolve/5be20db9509754dadad47689368639fcec739c00/miracl-v1.0-ko/qrels/qrels.miracl-v1.0-ko-dev.tsv'}, 'topics.miracl-v1.0-ko-dev.tsv': {'sha256': 'a365552cfc997a8915e948a3b5994883f641e7c3f12b6af87bbfaf89729e32a8', 'url': 'https://huggingface.co/datasets/miracl/miracl/resolve/5be20db9509754dadad47689368639fcec739c00/miracl-v1.0-ko/topics/topics.miracl-v1.0-ko-dev.tsv'}}, 'selection': 'first 12 topics in source order; all judged passages; no outcome-dependent replacement', 'selection_commit': '174d0ee93c745849ca584a13b8ca57dda579187e', 'shards': [{'lfs': {'oid': 'c56a31883a291504aa9c97968fb7a5fbcc9ea1099ee1810200249e1afb7fc55d', 'pointerSize': 133, 'size': 87965596}, 'oid': '81347d130419cc4f12e43c5456f3bb90951198db', 'path': 'miracl-corpus-v1.0-ko/docs-0.jsonl.gz', 'size': 87965596, 'type': 'file', 'xetHash': '286708b9ad1bea29e5261b2d4f13ff887dcfaff0d4af2db47374a66e3a314780'}, {'lfs': {'oid': 'fecd2886124e78c3aa87c59604ac9909c23165415c70a96f4edb95677b5ed0cd', 'pointerSize': 133, 'size': 75422723}, 'oid': '613109fef41003013e0d3a3fa7185bfe7323ddc8', 'path': 'miracl-corpus-v1.0-ko/docs-1.jsonl.gz', 'size': 75422723, 'type': 'file', 'xetHash': '50a28a6dfbddf568a64e114061475643757a4ad6a4c623f3f2d1c69d360ec712'}, {'lfs': {'oid': '93e90d098d78f50a9e76dd2e64608d65e0563787954f848da9b04286f81b75d9', 'pointerSize': 133, 'size': 62582229}, 'oid': 'dd4674fb4ba81d838f5753afd6e77aa39a4320ee', 'path': 'miracl-corpus-v1.0-ko/docs-2.jsonl.gz', 'size': 62582229, 'type': 'file', 'xetHash': '1164c8b717d650b36a1c794315589ba5a6e934ca8bdcaa00b058b2b37742e712'}], 'topics_qrels_revision': '5be20db9509754dadad47689368639fcec739c00'}

def normalize_query(text):
    return " ".join(unicodedata.normalize("NFKC",text).casefold().split())

def select_miracl(topics_text, qrels_text, documents, count=12):
    topics = [line.split('\t', 1) for line in topics_text.splitlines()][:count]
    if type(count) is not int or count < 1 or len(topics) != count:
        raise ValueError('requested topic count unavailable')
    if any(len(row) != 2 or not all(v.strip() for v in row) for row in topics):
        raise ValueError('invalid topic row')
    if (len({q for q, _ in topics}) != count
            or len({normalize_query(t) for _, t in topics}) != count):
        raise ValueError('duplicate topics; do not replace after selection')
    judgments = {q: {} for q, _ in topics}
    for line in qrels_text.splitlines():
        qid, _, docid, grade = line.split()
        if qid in judgments:
            if grade not in ('0', '1') or docid in judgments[qid]:
                raise ValueError('invalid or duplicate judgment')
            judgments[qid][docid] = int(grade)
    if any(not row for row in judgments.values()):
        raise ValueError('missing judgments for selected topic')
    wanted = {docid for row in judgments.values() for docid in row}
    pool = {}
    for doc in documents:
        if doc['docid'] in wanted:
            if doc['docid'] in pool:
                raise ValueError('duplicate corpus document')
            if not doc['title'] or not doc['text']:
                raise ValueError('empty corpus document')
            pool[doc['docid']] = doc
    if set(pool) != wanted:
        raise ValueError('missing judged documents')
    return dict(topics=topics, judgments=judgments, documents=pool)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def verify(path,expected):
    actual=sha(path)
    if actual!=expected:raise ValueError('checksum mismatch')
    return actual

def download(url,path,expected,size=None):
    # One attempt. Standard redirect handling only; no retry or model/key access.
    request=urllib.request.Request(url,headers={'User-Agent':'MIRACL-pinned-restoration/1.0'})
    with urllib.request.urlopen(request,timeout=60) as response,path.open('xb') as f:
        shutil.copyfileobj(response,f,1024*1024)
    if size is not None and path.stat().st_size!=size:raise ValueError('size mismatch')
    return {'url':url,'sha256':verify(path,expected),'bytes':path.stat().st_size}

class RestorationValidationError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def preserve_selected(selected,source,log,out,public_key=PUBLIC_KEY,selection_error=None):
    """Always seal diagnostics before refusing an unvalidated extraction.

    A hash failure never produces a normal selected.json archive entry.
    Caller must keep artifact upload enabled on failure; nothing is certified.
    """
    from capsule import seal
    selected_bytes=None if selected is None else (json.dumps(selected,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    actual=None if selected_bytes is None else hashlib.sha256(selected_bytes).hexdigest()
    canonical=None if selected is None else hashlib.sha256(json.dumps(selected,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
    error=selection_error
    if error is None and actual!=SELECTED_SHA256:error='SELECTED_SHA256_MISMATCH'
    if error is None and (len(selected['topics'])!=12 or len(selected['documents'])!=168):error='SELECTED_SHAPE_MISMATCH'
    verified=error is None
    provenance={'schema_version':'miracl-restore-diagnostic-v2','status':'VERIFIED_ORIGINAL_BYTES' if verified else 'QUARANTINED_NOT_VALIDATED',
      'safe_error_code':error,'source_manifest':MANIFEST,'verified_downloads':log,
      'expected_selected_sha256':SELECTED_SHA256,'actual_selected_sha256':actual,
      'expected_canonical_sha256':EXPECTED_CANONICAL_SHA256,'actual_canonical_sha256':canonical,
      'selected_hash_verified':verified,'canonical_hash_matches':canonical==EXPECTED_CANONICAL_SHA256,
      'selected_bytes':None if selected_bytes is None else len(selected_bytes),
      'query_count':None if selected is None else len(selected['topics']),
      'document_count':None if selected is None else len(selected['documents']),
      'selection':'first12 source order, all upstream judged documents, original labels unchanged',
      'scoring_runs':0,'llm_calls':0,'extractor':'copied original external_data.select_miracl; original normalize_query NFKC/casefold/whitespace',
      'diagnostic_restriction':'On mismatch retain bytes only for independent diagnosis; never substitute expected hash, score, or mark original restoration complete.'}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        if selected_bytes is not None:z.writestr('selected.json' if verified else 'quarantine/selected.json',selected_bytes)
        z.writestr('provenance.json',json.dumps(provenance,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
        for path in sorted(source.iterdir()):z.write(path,'source/'+path.name)
    wire=seal(public_key,buffer.getvalue(),CONTEXT)
    with out.open('xb') as f:f.write(wire)
    out.chmod(0o600)
    if not verified:raise RestorationValidationError(error)

def main():
    runner=Path(os.environ['RUNNER_TEMP'])
    out=runner/'miracl-restored.enc'
    if out.exists():raise FileExistsError('output exists')
    with tempfile.TemporaryDirectory(prefix='miracl-private-',dir=runner) as tmp:
        root=Path(tmp);source=root/'source';source.mkdir();log={}
        for index,(name,info) in enumerate(MANIFEST['files'].items(),1):
            log[name]=download(info['url'],source/name,info['sha256'])
            print('Verified source metadata '+str(index)+'/4',flush=True)
        shards=[]
        for index,info in enumerate(MANIFEST['shards'],1):
            path=root/('miracl-ko-'+Path(info['path']).name)
            url='https://huggingface.co/datasets/miracl/miracl-corpus/resolve/'+MANIFEST['corpus_revision']+'/'+info['path']
            log[path.name]=download(url,path,info['lfs']['oid'],info['size'])
            shards.append(path);print('Verified corpus shard '+str(index)+'/3',flush=True)
        def documents():
            for path in shards:
                with gzip.open(path,'rt',encoding='utf-8') as f:
                    for line in f:yield json.loads(line)
        try:
            selected=select_miracl((source/'topics.miracl-v1.0-ko-dev.tsv').read_text(encoding='utf-8'),(source/'qrels.miracl-v1.0-ko-dev.tsv').read_text(encoding='utf-8'),documents())
        except ValueError as exc:
            known={'requested topic count unavailable':'TOPIC_COUNT_UNAVAILABLE','invalid topic row':'INVALID_TOPIC_ROW','duplicate topics; do not replace after selection':'DUPLICATE_TOPICS','invalid or duplicate judgment':'INVALID_OR_DUPLICATE_JUDGMENT','missing judgments for selected topic':'MISSING_JUDGMENTS','duplicate corpus document':'DUPLICATE_CORPUS_DOCUMENT','empty corpus document':'EMPTY_CORPUS_DOCUMENT','missing judged documents':'MISSING_JUDGED_DOCUMENTS'}
            preserve_selected(None,source,log,out,selection_error=known.get(str(exc),'SELECTION_VALUE_ERROR'))
            raise
        preserve_selected(selected,source,log,out)
        print('Encrypted restoration artifact ready; no scoring or model calls.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Avoid document, request body, response body or secret-bearing diagnostics.
        code=exc.code if isinstance(exc,RestorationValidationError) else type(exc).__name__
        print('Restoration failed: '+code+'; encrypted diagnostic may be available.',file=sys.stderr)
        sys.exit(1)
