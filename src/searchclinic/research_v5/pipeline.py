"""Frozen offline candidate application. Final judgments enter only score_application.

SHA256 seals detect accidental changes; they are commitments, not signatures or
proof that a study was preregistered. This module never invokes a model.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path

from searchclinic.corpus.catalog import Document
from searchclinic.index.engine import SearchEngine
from searchclinic.research.phase2.contracts import Context
from .semantic import PROTOCOL_ID, SemanticInput, select_candidate

BUNDLE_KEYS = {'version', 'model_id', 'min_confidence', 'seed', 'documents', 'records'}
RECORD_KEYS = {'context', 'candidates', 'generation_error'}


def _encoded(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise ValueError('seal must contain finite JSON-compatible data') from exc


def freeze(body):
    """Return a detached JSON body and SHA256 commitment to its canonical bytes."""
    encoded = _encoded(body)
    return {'body': json.loads(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}


def verify(seal):
    """Verify exact seal fields and return a detached body."""
    if not isinstance(seal, dict) or set(seal) != {'body', 'sha256'}:
        raise ValueError('invalid seal envelope')
    checked = freeze(seal['body'])
    if seal['sha256'] != checked['sha256']:
        raise ValueError('seal hash mismatch')
    return checked['body']


def _keys(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'{label} has missing or unexpected fields')


def _runtime():
    root = Path(__file__).resolve().parents[1]
    # Hash only the declared application implementation, never label sources.
    names = ('__init__.py', 'corpus/__init__.py', 'patch/__init__.py',
             'index/__init__.py', 'analysis/__init__.py', 'research/__init__.py',
             'research/phase2/__init__.py', 'research_v5/__init__.py', 'analysis/jamo.py',
             'research_v5/pipeline.py', 'research_v5/semantic.py',
             'index/engine.py', 'index/bm25.py', 'analysis/analyzer.py',
             'analysis/config.py', 'patch/ir.py', 'corpus/catalog.py',
             'research/phase2/contracts.py', 'research/models.py', 'research/splits.py')
    sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    analyzer = root / 'analysis' / 'analyzer.py'
    return {'source_hash': freeze(sources)['sha256'], 'source_files': sources,
            'analyzer_hash': hashlib.sha256(analyzer.read_bytes()).hexdigest(),
            'kiwipiepy': version('kiwipiepy'), 'kiwipiepy_model': version('kiwipiepy_model')}


def _bundle(sealed):
    body = verify(sealed)
    _keys(body, BUNDLE_KEYS, 'candidate bundle')
    if body['version'] != 'v5' or not isinstance(body['model_id'], str) or not body['model_id'].strip():
        raise ValueError('invalid version/model identity')
    threshold = body['min_confidence']
    if (type(threshold) not in (int, float) or not math.isfinite(threshold)
            or not 0 <= threshold <= 1 or type(body['seed']) is not int):
        raise ValueError('invalid frozen confidence/seed')
    if not isinstance(body['documents'], list) or not body['documents']:
        raise ValueError('documents must be a nonempty list')
    docs = {}
    for raw in body['documents']:
        _keys(raw, {'doc_id', 'name', 'description', 'category'}, 'document')
        if any(not isinstance(v, str) for v in raw.values()) or not raw['doc_id'].strip():
            raise ValueError('document fields must be strings and ID nonempty')
        if raw['doc_id'] in docs:
            raise ValueError('duplicate document ID')
        docs[raw['doc_id']] = Document(**raw)
    if not isinstance(body['records'], list) or not body['records']:
        raise ValueError('records must be a nonempty list')
    records = {}
    for record in body['records']:
        _keys(record, RECORD_KEYS, 'candidate record')
        context = Context.model_validate(record['context'], strict=True)
        if context.query_id in records:
            raise ValueError('duplicate record query ID')
        if record['generation_error'] is not None and not isinstance(record['generation_error'], str):
            raise ValueError('generation_error must be string or null')
        if not isinstance(record['candidates'], list) or len(record['candidates']) > 3:
            raise ValueError('at most three ordered candidates required')
        for evidence in context.documents:
            if evidence.doc_id not in docs or evidence.text != docs[evidence.doc_id].text:
                raise ValueError('evidence document absent from corpus or text mismatch')
        records[context.query_id] = (context, record)
    return body, docs, records


def _validated(context, raw):
    # Validate one candidate at a time: malformed siblings never hide good ones.
    checked = SemanticInput(context=context, prescription=raw).prescription
    terms = [word.form for word in checked.user_words]
    terms += [term for group in checked.synonym_groups for term in group.terms]
    terms += [term for compound in checked.compound_expansions for term in [compound.word, *compound.parts]]
    sources = [context.query, *(doc.text for doc in context.documents)]
    if any(not any(term in text for text in sources) for term in terms):
        raise ValueError('candidate term has no literal evidence')
    return checked


def _rank(engine, query):
    return [hit.doc_id for hit in engine.search(query, k=10)]


def _patched(base, context, prescription):
    if prescription.target_query != context.query:
        raise ValueError('candidate target mismatch')
    return _rank(base.with_config(prescription.apply_to(base.config)), context.query)


def apply_candidates(bundle, verdicts, *, condition='rubric', policy='semantic'):
    """Apply independently to immutable base engines; never accept final labels.

    Verdict lists retain original candidate positions; absent trailing verdicts
    hold. Every query requires an explicit list (possibly empty). ``first_valid``
    is an explicitly labeled ablation without semantic verification.
    """
    body, docs, records = _bundle(bundle)
    if condition not in ('pair', 'context', 'rubric') or policy not in ('semantic', 'first_valid'):
        raise ValueError('unsupported condition/policy')
    if not isinstance(verdicts, dict) or set(verdicts) != set(records):
        raise ValueError('verdicts must cover exactly every query ID')
    base = SearchEngine(list(docs.values()))
    rankings, baseline, decisions = {}, {}, {}
    for qid, (context, record) in records.items():
        submitted = verdicts[qid]
        if not isinstance(submitted, list) or len(submitted) > len(record['candidates']):
            raise ValueError('verdicts must be an aligned list no longer than candidates')
        baseline[qid] = _rank(base, context.query)
        candidate_decisions, eligible = [], []
        for index, raw in enumerate(record['candidates']):
            decision = {'candidate_index': index, 'eligible': False, 'errors': [], 'confidence': None}
            if record['generation_error'] is not None:
                decision['errors'].append('generation_error')
                candidate_decisions.append(decision)
                continue
            try:
                prescription = _validated(context, raw)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                decision['errors'].append(f'invalid_candidate: {exc}')
                candidate_decisions.append(decision)
                continue
            if policy == 'first_valid':
                decision['eligible'] = True
            else:
                raw_verdict = submitted[index] if index < len(submitted) else None
                selected = select_candidate(context, [raw], [raw_verdict], condition=condition,
                                            min_confidence=body['min_confidence'], require_context=condition != 'pair')
                assessed = selected.candidate_decisions[0]
                decision.update(eligible=assessed.eligible, confidence=assessed.confidence,
                                errors=list(assessed.reasons), request_hash=assessed.request_hash,
                                model_id=assessed.model_id)
                if assessed.model_id is not None and assessed.model_id != body['model_id']:
                    decision['eligible'] = False
                    decision['errors'].append('model_id_mismatch')
            candidate_decisions.append(decision)
            if decision['eligible']:
                eligible.append((index, prescription, decision['confidence'] or 0))
        chosen = min(eligible, key=lambda item: (-(item[2] if policy == 'semantic' else 0), item[0])) if eligible else None
        rankings[qid] = baseline[qid]
        chosen_index = None
        if chosen:
            try:
                rankings[qid] = _patched(base, context, chosen[1])
                chosen_index = chosen[0]
            except (ValueError, TypeError, RuntimeError) as exc:
                candidate_decisions[chosen[0]]['eligible'] = False
                candidate_decisions[chosen[0]]['errors'].append(f'application_error: {exc}')
        decisions[qid] = {'candidate_index': chosen_index, 'candidate_decisions': candidate_decisions,
                          'generation_error': record['generation_error'],
                          'status': 'selected' if chosen_index is not None else 'held'}
    protocol = {k: body[k] for k in ('version', 'model_id', 'min_confidence', 'seed')}
    protocol.update(condition=condition, policy=policy, semantic_protocol_id=PROTOCOL_ID)
    return freeze({'version': 'application-v5', 'input_hash': bundle['sha256'],
                   'verdict_hash': freeze(verdicts)['sha256'], 'protocol': protocol,
                   'runtime': _runtime(), 'rankings': rankings,
                   'baseline_rankings': baseline, 'decisions': decisions})


def diagnostic_candidates(bundle):
    """Replay every structurally/literally valid candidate separately, without labels."""
    _, docs, records = _bundle(bundle)
    base = SearchEngine(list(docs.values()))
    rankings, baseline, errors = {}, {}, {}
    generation_errors, statuses = {}, {}
    for qid, (context, record) in records.items():
        rankings[qid], errors[qid] = {}, {}
        generation_errors[qid] = record['generation_error']
        baseline[qid] = _rank(base, context.query)
        for index, raw in enumerate(record['candidates']):
            if record['generation_error'] is not None:
                errors[qid][str(index)] = 'generation_error'
                continue
            try:
                rankings[qid][str(index)] = _patched(base, context, _validated(context, raw))
            except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
                errors[qid][str(index)] = str(exc)
        statuses[qid] = ('generation_error' if record['generation_error'] is not None else
                         'abstained' if not record['candidates'] else
                         'candidates_replayed' if rankings[qid] else 'all_candidates_invalid')
    return freeze({'version': 'diagnostic-candidates-v5', 'diagnostic_only': True,
                   'input_hash': bundle['sha256'], 'runtime': _runtime(),
                   'rankings': rankings, 'baseline_rankings': baseline, 'errors': errors,
                   'generation_errors': generation_errors, 'statuses': statuses})


def score_application(application, queries, qrels, **kwargs):
    """Separate offline evaluator; labels cannot change already sealed decisions."""
    from .evaluation import score_runs
    body = verify(application)
    _keys(body, {'version', 'input_hash', 'verdict_hash', 'protocol', 'runtime',
                 'rankings', 'baseline_rankings', 'decisions'}, 'application')
    if body['version'] != 'application-v5':
        raise ValueError('expected a frozen v5 application')
    _keys(body['protocol'], {'version', 'model_id', 'min_confidence', 'seed',
                            'condition', 'policy', 'semantic_protocol_id'}, 'application protocol')
    if body['runtime'] != _runtime():
        raise ValueError('application source/analyzer identity changed')
    if any(not isinstance(body[k], dict) for k in ('decisions', 'rankings', 'baseline_rankings')):
        raise ValueError('application decisions and rankings must be mappings')
    if set(body['decisions']) != set(body['rankings']):
        raise ValueError('decision query coverage mismatch')
    for decision in body['decisions'].values():
        _keys(decision, {'candidate_index', 'candidate_decisions', 'generation_error', 'status'}, 'decision')
        if not isinstance(decision['candidate_decisions'], list):
            raise ValueError('candidate decisions must be a list')
        for candidate in decision['candidate_decisions']:
            required = {'candidate_index', 'eligible', 'errors', 'confidence'}
            optional = {'request_hash', 'model_id'}
            if (not isinstance(candidate, dict) or not required <= set(candidate)
                    or set(candidate) - required - optional):
                raise ValueError('candidate decision has missing or unexpected fields')
    scores = score_runs(queries, qrels, {'no_repair': body['baseline_rankings'],
                                       'selected': body['rankings']}, **kwargs)
    return freeze({'version': 'scores-v5', 'application_hash': application['sha256'],
                   'input_hash': body['input_hash'], 'scores': scores})
