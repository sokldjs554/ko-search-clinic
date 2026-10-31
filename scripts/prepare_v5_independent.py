#!/usr/bin/env python3
"""Download pinned free KLUE data and prepare local candidate review materials.

No LLM/API provider calls, model execution, credentials, scoring or final labels.
Detailed source, query, passage and proxy judgments stay under ignored work/.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.research_v5.dataset import (SOURCE_URL, SOURCE_SHA256, README_URL, README_SHA256,
                                             file_hash, prepare)


def source_cache(cache, download):
    cache.mkdir(parents=True, exist_ok=True)
    for name, url, checksum in [('klue-mrc-v1.1_dev.json', SOURCE_URL, SOURCE_SHA256),
                                ('README.md', README_URL, README_SHA256)]:
        path = cache/name
        if not path.exists():
            if not download:
                raise ValueError(f'missing source cache {name}; explicitly use --download once')
            request = urllib.request.Request(url, headers={'User-Agent': 'ko-search-clinic-v5-source-preparation'})
            # Public fixed URLs; urllib honors the managed environment proxy.
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(32*1024*1024+1)
            if len(data) > 32*1024*1024:
                raise ValueError('source download exceeds 32 MiB bound')
            import hashlib
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError('download source checksum mismatch')
            with path.open('xb') as stream:
                stream.write(data)
        if file_hash(path) != checksum:
            raise ValueError(f'cached source checksum mismatch: {name}')
    return cache/'klue-mrc-v1.1_dev.json'


def known_exposure():
    """Whitelist identities/text only; do not consult prior retrieval outcomes."""
    docs = load_catalog()
    exposure = [{'query_id': f'controlled36:{i}', 'query': q.query,
                 'document_texts': [], 'concept_ids': []} for i, q in enumerate(load_evalset())]
    exposure.append({'query_id': 'controlled36:catalog', 'query': '',
                     'document_texts': [d.text for d in docs], 'concept_ids': [d.name for d in docs]})
    catalog_digest_input = json.dumps([asdict(d) for d in docs], ensure_ascii=False, sort_keys=True)
    import hashlib
    sources = [{'source': 'current controlled36 catalog/evalset', 'query_count': len(exposure)-1,
                'document_count': len(docs),
                'catalog_canonical_sha256': hashlib.sha256(catalog_digest_input.encode()).hexdigest(),
                'coverage': 'complete current 36 query identities and catalog text; semantic concepts uncertified'}]
    topics = ROOT/'artifacts/research/phase2-miracl-ko-12/source/topics.miracl-v1.0-ko-dev.tsv'
    lines = topics.read_text(encoding='utf-8').splitlines()
    for line in lines:
        qid, query = line.split('\t', 1)
        exposure.append({'query_id': 'miracl-ko-dev:'+qid, 'query': query,
                         'document_texts': [], 'concept_ids': []})
    sources.append({'source': str(topics.relative_to(ROOT)), 'sha256': file_hash(topics),
                    'query_count': len(lines),
                    'coverage': 'all available source topics, broader than selected12; document text unavailable'})
    return exposure, sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT/'work/v5-independent-source')
    parser.add_argument('--out', type=Path, default=ROOT/'work/v5-independent-klue-v2')
    parser.add_argument('--download', action='store_true', help='download fixed public source files if absent')
    parser.add_argument('--extra-exposure', type=Path, help='local JSON list of query/document_texts/concept_ids; never certifies missing120 coverage')
    args = parser.parse_args(argv)
    # A typo must not place detailed evaluation data in tracked public paths.
    local_root = (ROOT/'work').resolve()
    for path in (args.cache, args.out):
        if not path.resolve().is_relative_to(local_root):
            parser.error('cache and output must be under this repository ignored work/ directory')
    source = source_cache(args.cache, args.download)
    exposure, sources = known_exposure()
    if args.extra_exposure:
        extra = json.loads(args.extra_exposure.read_text(encoding='utf-8'))
        if not isinstance(extra, list):
            raise ValueError('extra exposure must be a list')
        exposure.extend(extra)
        sources.append({'source': str(args.extra_exposure), 'sha256': file_hash(args.extra_exposure),
                        'coverage': 'user supplied partial inventory; requires independent completeness review'})
    summary = prepare(source, args.out, exposure=exposure, exposure_sources=sources)
    print(json.dumps({'output_dir': str(args.out), **summary}, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
