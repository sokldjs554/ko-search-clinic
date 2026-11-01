"""Free preparation CLI. No labels argument, paid transport, or scoring path."""
import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from searchclinic.corpus.catalog import Document
from searchclinic.research.costs import CostRecord, MeasuredEngine
from searchclinic.research.splits import digest, normalize_query

from .contracts import source_provenance
from .generation import build_context, build_llm_request, generate_in_process, public_input_manifest, seal_bundle, write_once


def prepare(corpus_path, stimuli_path, label_commitment, out):
    out=Path(out)
    if out.exists():
        raise FileExistsError('use a new output directory; prior candidates must not be overwritten')
    if not re.fullmatch('[0-9a-f]{64}',label_commitment):
        raise ValueError('label SHA256 commitment required; label contents are not accepted')
    corpus=json.loads(Path(corpus_path).read_text(encoding='utf-8'))
    stimuli=json.loads(Path(stimuli_path).read_text(encoding='utf-8'))
    documents=corpus['documents']
    docs=[Document(**{k:d[k] for k in ('doc_id','name','description','category')}) for d in documents]
    queries=stimuli['queries']
    if not queries or len({q['query_id'] for q in queries})!=len(queries):
        raise ValueError('nonempty unique stimulus IDs required')
    if len({normalize_query(q['query']) for q in queries})!=len(queries):
        raise ValueError('duplicate normalized query')
    start=perf_counter()
    engine=MeasuredEngine(docs)
    contexts=[build_context(engine,q['query_id'],q['query']) for q in queries]
    preparation_costs=asdict(CostRecord(search_calls=engine.meter.search_calls,
        reindexes=engine.meter.reindexes,latency_ms=(perf_counter()-start)*1000))
    dataset_hash=digest({'corpus':corpus,'stimuli':stimuli})
    # Freeze public inputs before any candidate generation. This separate file is
    # an evaluator-trusted commitment, not a self-certifying mutable bundle hash.
    initial=seal_bundle(contexts,{},documents,dataset_hash,label_commitment)
    write_once(out/'public-input-manifest.json',public_input_manifest(initial))
    records=[generate_in_process(c) for c in contexts]
    sealed=seal_bundle(contexts,{'rules_plus':records},documents,dataset_hash,label_commitment)
    requests=[{'query_id':c.query_id,'context_hash':r['context_hash'],
        'request':build_llm_request(c),'requires_call':r['detection']['predicted_failure'] is True}
        for c,r in zip(contexts,records)]
    write_once(out/'rules-preparation.json',sealed)
    write_once(out/'llm-requests.json',requests)
    status={'paid_calls':0,'final_evaluation':'not_run','llm_candidates':'not_generated',
        'data_review':'not_certified','query_count':len(queries),'document_count':len(documents),
        'potential_llm_test_calls':sum(r['requires_call'] for r in requests),
        'maximum_test_calls':len(queries),'shared_preparation_costs':preparation_costs,
        'candidate_seal_hash':sealed['seal_hash'],'dataset_hash':sealed['body']['dataset_hash'],
        **source_provenance()}
    write_once(out/'status.json',status)
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare')
    for name in ('corpus','stimuli','label-commitment','out'):
        prep.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=prepare(args.corpus,args.stimuli,args.label_commitment,args.out)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
