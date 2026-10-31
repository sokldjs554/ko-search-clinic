"""Source-driven Korean QA-proxy candidate data; no retrieval or model calls.

Sparse source QA labels deliberately cannot be passed directly to score_runs.
The private proxy file is not a final retrieval relevance judgment set.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unicodedata

from .evaluation import audit_splits

REVISION = '3efd98708a40ff49251fddde35453f8fbb11f536'
SOURCE_SHA256 = 'b31bb073e47cdeb19f2f1bae03d916ecabf945140334c75842d6994f700d4f47'
README_SHA256 = '1f87facecc35feabf8ad25ecd2eda75bab8ea3ad074569b5239b4d57197ea059'
SOURCE_URL = f'https://raw.githubusercontent.com/KLUE-benchmark/KLUE/{REVISION}/klue_benchmark/klue-mrc-v1.1/klue-mrc-v1.1_dev.json'
README_URL = f'https://raw.githubusercontent.com/KLUE-benchmark/KLUE/{REVISION}/README.md'
SEED = 'ko-search-clinic-v5-independent-20261031'


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rank(namespace, value):
    return digest(SEED + ':' + namespace + ':' + value)


def _source_rows(source):
    rows, docs, seen_ids, seen_queries = [], {}, set(), set()
    # Connected title/context groups prevent identical text under different
    # titles, and distinct paragraphs under one title, from crossing splits.
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for article in source['data']:
        title = article['title']
        if not isinstance(title, str):
            raise ValueError('article title must be a string')
        title_key = ('title:' + digest(normalized(title)) if normalized(title) else
                     'untitled-article:' + digest(json.dumps(sorted(normalized(p['context'])
                                                                  for p in article['paragraphs']))))
        for paragraph in article['paragraphs']:
            context = paragraph['context']
            if not isinstance(context, str) or not normalized(context):
                raise ValueError('empty document context')
            doc_id = 'klue:' + digest(normalized(context))
            left, right = find(title_key), find(doc_id)
            parent[max(left, right)] = min(left, right)
            doc = {'doc_id': doc_id, 'name': title, 'description': context,
                   'category': article.get('source', 'klue'), 'group_key': title_key}
            # Canonical title choice makes the bytes invariant to source order.
            if doc_id not in docs or title < docs[doc_id]['name']:
                docs[doc_id] = doc
            for qa in paragraph['qas']:
                qid, question = qa['guid'], qa['question']
                if not isinstance(qid, str) or not qid or not isinstance(question, str) or not normalized(question):
                    raise ValueError('invalid query identity')
                if qid in seen_ids or normalized(question) in seen_queries:
                    raise ValueError('duplicate query identity or text')
                seen_ids.add(qid); seen_queries.add(normalized(question))
                impossible = qa['is_impossible']
                if type(impossible) is not bool:
                    raise ValueError('is_impossible must be boolean')
                if not impossible:
                    if not qa['answers']:
                        raise ValueError('missing answer span')
                    for answer in qa['answers']:
                        start, text = answer['answer_start'], answer['text']
                        if type(start) is not int or start < 0 or not text or context[start:start+len(text)] != text:
                            raise ValueError('invalid answer span')
                rows.append({'query_id': qid, 'query': question, 'source_doc_id': doc_id,
                             'is_impossible': impossible, 'answers': qa['answers'],
                             'question_type': qa.get('question_type'), 'group_key': title_key})
    for row in [*rows, *docs.values()]:
        row['concept_id'] = 'article-component:' + digest(find(row.pop('group_key')))
    return rows, docs


def build_dataset(source, *, answerable=160, unanswerable=40, calibration=40,
                  distractors=100, exposure=()):
    """Select by fixed hashes and source answerability, never by arm scores.

    Exactly one query is selected per connected article/document group. A group
    containing both QA types is claimed by answerable selection first. Other
    groups supply distractor documents, whose cross-query relevance is unknown.
    """
    for key, value in [('answerable', answerable), ('unanswerable', unanswerable),
                       ('calibration', calibration), ('distractors', distractors)]:
        if type(value) is not int or value < 0:
            raise ValueError(f'{key} must be nonnegative integer')
    if not 0 < calibration < answerable + unanswerable:
        raise ValueError('calibration must leave both splits nonempty')
    rows, docs = _source_rows(source)
    selected, used_groups = [], set()
    for impossible, count in [(False, answerable), (True, unanswerable)]:
        candidates = sorted((r for r in rows if r['is_impossible'] == impossible),
                            key=lambda r: (_rank('query', r['query_id']), r['query_id']))
        chosen = []
        for row in candidates:
            if len(chosen) == count:
                break
            if row['concept_id'] not in used_groups:
                chosen.append(row.copy()); used_groups.add(row['concept_id'])
        if len(chosen) != count:
            raise ValueError('insufficient independent source groups')
        selected.extend(chosen)
    selected.sort(key=lambda r: (_rank('split', r['concept_id']), r['query_id']))
    for i, row in enumerate(selected):
        row['split'] = 'calibration' if i < calibration else 'candidate_final'
    pool = {r['source_doc_id']: {**docs[r['source_doc_id']], 'split': r['split']} for r in selected}
    added = 0
    for doc in sorted(docs.values(), key=lambda d: (_rank('distractor', d['doc_id']), d['doc_id'])):
        if added == distractors:
            break
        if doc['concept_id'] in used_groups:
            continue
        split = 'calibration' if added < distractors * calibration // len(selected) else 'candidate_final'
        pool[doc['doc_id']] = {**doc, 'split': split}
        used_groups.add(doc['concept_id']); added += 1
    if added != distractors:
        raise ValueError('insufficient distractor source groups')
    queries = [{k: r[k] for k in ('query_id', 'query', 'split', 'concept_id')} for r in selected]
    split_records = {split: [{'query_id': r['query_id'], 'query': r['query'],
                             'document_ids': [r['source_doc_id']], 'concept_ids': [r['concept_id']]}
                            for r in selected if r['split'] == split]
                     for split in ('calibration', 'candidate_final')}
    split_audit = audit_splits(split_records)
    # Also audit every distractor's article/document ownership, not just qrels.
    owners = {}
    for doc in pool.values():
        previous = owners.setdefault(doc['concept_id'], doc['split'])
        if previous != doc['split']:
            raise ValueError('distractor concept crossed splits')
    historical_queries = {normalized(r['query']) for r in exposure if r.get('query')}
    historical_docs = {normalized(t) for r in exposure for t in r.get('document_texts', [])}
    historical_concepts = {normalized(t) for r in exposure for t in r.get('concept_ids', [])}
    query_overlap = [r['query_id'] for r in selected if normalized(r['query']) in historical_queries]
    doc_overlap = [d['doc_id'] for d in pool.values()
                   if normalized(d['description']) in historical_docs or normalized(d['name']+' '+d['description']) in historical_docs]
    concept_overlap = [d['doc_id'] for d in pool.values() if normalized(d['name']) in historical_concepts]
    audit = {'study_status': 'candidate_review_pending', 'final_evaluation_ready': False,
             'blind_independence_certified': False, 'complete_historical_exposure_audited': False,
             'split_audit': split_audit, 'all_corpus_document_group_split_audit_valid': True,
             'known_exposure_overlaps': {'query_count': len(query_overlap), 'document_count': len(doc_overlap),
                                        'title_concept_count': len(concept_overlap)},
             'known_exposure_record_count': len(exposure),
             'known_exposure_unique_queries': len(historical_queries),
             'known_exposure_unique_document_texts': len(historical_docs),
             'known_exposure_unique_concept_strings': len(historical_concepts),
             'semantic_concept_overlap_review': 'pending; article groups are proxies, not certified concepts',
             'unanswerable_policy': 'excluded_pending_all_pairs_human_review; source passage only is known negative',
             'label_semantics': 'sparse_source_QA_answerability_proxy_not_retrieval_qrels',
             'unjudged_policy': 'unknown; never converted to relevance zero',
             'selection_before_any_retrieval_scores': True, 'provider_calls_executed': 0,
             'retrieval_scoring_executed': False}
    return {'queries': queries, 'documents': sorted(pool.values(), key=lambda d: d['doc_id']),
            'proxy_qrels': {r['query_id']: {r['source_doc_id']: int(not r['is_impossible'])} for r in selected},
            'source_annotations': selected, 'audit': audit,
            'overlap_details': {'query_ids': query_overlap, 'document_ids': doc_overlap,
                                'title_concept_doc_ids': concept_overlap},
            'source_counts': {'queries': len(rows), 'documents': len(docs),
                              'answerable': sum(not r['is_impossible'] for r in rows),
                              'unanswerable': sum(r['is_impossible'] for r in rows)}}


def _write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def prepare(source_path, output, *, expected_sha256=SOURCE_SHA256, exposure=(), exposure_sources=(), **selection):
    """Write immutable local preparation, blank review grids and hash manifest."""
    source_path, output = Path(source_path), Path(output)
    if file_hash(source_path) != expected_sha256:
        raise ValueError('source checksum mismatch')
    data = build_dataset(json.loads(source_path.read_text(encoding='utf-8')), exposure=exposure, **selection)
    output.mkdir(parents=True, exist_ok=False)
    private, review = output/'private', output/'review'
    private.mkdir(); review.mkdir()
    # Independently namespaced opaque IDs: no source GUID, article component,
    # or qrel-derived query/document relationship in reviewer/selector inputs.
    query_ids = {q['query_id']: 'query:' + digest('public-query:' + q['query_id']) for q in data['queries']}
    doc_ids = {d['doc_id']: 'document:' + digest('public-document:' + d['doc_id']) for d in data['documents']}
    public_queries = [{'query_id': query_ids[q['query_id']], 'query': q['query'], 'split': q['split']}
                      for q in data['queries']]
    public_documents = [{**{k: d[k] for k in ('name', 'description', 'category', 'split')},
                         'doc_id': doc_ids[d['doc_id']]} for d in data['documents']]
    _write(output/'inputs.json', {'queries': public_queries, 'documents': public_documents})
    _write(private/'identity-split-audit.json', {
        'queries': [{'query_id': query_ids[q['query_id']], 'source_query_id': q['query_id'],
                     'answer_source_document_id': doc_ids[q['source_doc_id']],
                     'concept_id': q['concept_id'], 'split': q['split']}
                    for q in data['source_annotations']],
        'documents': [{'doc_id': doc_ids[d['doc_id']], 'source_doc_id': d['doc_id'],
                       'concept_id': d['concept_id'], 'split': d['split']}
                      for d in data['documents']]})
    _write(private/'source-proxy-labels.json', {k: data[k] for k in ('proxy_qrels', 'source_annotations')})
    _write(private/'exposure-overlap-details.json', data['overlap_details'])
    _write(private/'known-exposure.json', list(exposure))
    _write(output/'audit.json', data['audit'])
    _write(output/'selection.json', {'seed': SEED, 'method': 'SHA256_source_id_ranking_one_query_per_connected_title_context_group',
                                    'answerability_order': ['answerable', 'unanswerable'],
                                    'replacement_after_scores': False, 'source_counts': data['source_counts'],
                                    'parameters': {'answerable': 160, 'unanswerable': 40, 'calibration': 40,
                                                   'distractors': 100, **selection}})
    pairs = [(q['query_id'], d['doc_id'], q['split']) for q in public_queries for d in public_documents if q['split'] == d['split']]
    for reviewer in ('a', 'b'):
        with (review/f'reviewer-{reviewer}-pairs.csv').open('x', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['query_id', 'doc_id', 'split', 'reviewer_id', 'grade', 'evidence', 'ambiguity', 'reviewed_at_utc'])
            for qid, did, split in sorted(pairs, key=lambda pair: _rank('review-'+reviewer, pair[0]+pair[1])):
                writer.writerow([qid, did, split, '', '', '', '', ''])
    with (review/'query-review.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['query_id', 'reviewer_id', 'semantic_concept', 'ambiguity', 'eligibility', 'reason', 'reviewed_at_utc'])
        writer.writerows([q['query_id'], '', '', '', '', '', ''] for q in public_queries)
    _write(review/'attestation-template.json', {
        'status': 'pending', 'independent_reviewers': [], 'review_completed': False,
        'complete_historical_exposure_audited': False, 'past120_exposure_inventory_sha256': None,
        'unjudged_pairs_remaining': len(pairs), 'disagreement_count': None,
        'adjudicator_id': None, 'adjudication_completed': False,
        'final_labels_sha256': None, 'semantic_concept_review_completed': False,
        'final_evaluation_ready': False})
    summary = {'study_status': 'candidate_review_pending', 'final_evaluation_ready': False,
               'query_count': len(data['queries']), 'document_count': len(data['documents']),
               'source_positive_pairs': sum(next(iter(q.values())) == 1 for q in data['proxy_qrels'].values()),
               'source_negative_pairs': sum(next(iter(q.values())) == 0 for q in data['proxy_qrels'].values()),
               'review_pairs_per_reviewer': len(pairs), 'source_unjudged_pairs_in_split_corpora': len(pairs)-len(data['queries']),
               'splits': {s: {'queries': sum(q['split'] == s for q in data['queries']),
                               'documents': sum(d['split'] == s for d in data['documents'])}
                          for s in ('calibration', 'candidate_final')},
               'provider_calls_executed': 0, 'human_reviews_completed': 0}
    _write(output/'summary.json', summary)
    files = {str(path.relative_to(output)): file_hash(path) for path in sorted(output.rglob('*')) if path.is_file()}
    _write(output/'manifest.json', {
        'dataset': 'KLUE MRC v1.1 dev QA-proxy candidate', 'revision': REVISION,
        'source_url': SOURCE_URL, 'source_sha256': expected_sha256,
        'source_bytes': source_path.stat().st_size, 'license': 'CC-BY-SA-4.0',
        'license_evidence_url': README_URL, 'license_evidence_sha256': README_SHA256,
        'exposure_sources': list(exposure_sources),
        'unavailable_exposure': ['prior encrypted 120 query/document/concept inventory',
                                  'MIRACL pilot selected document text corpus'],
        'files_sha256': files, 'summary': summary})
    return summary
