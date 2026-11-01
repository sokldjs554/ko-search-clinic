"""Pinned MIRACL pilot extraction, without retrieval, repairs, or relabeling."""
import gzip
import hashlib
import json
from pathlib import Path

from searchclinic.research.splits import normalize_query


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


def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open(mode='rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def rebuild(source, cache):
    """Use locally downloaded, hash-verified source bytes; never fetch latest."""
    source, cache = Path(source), Path(cache)
    manifest = json.loads((source/'source-manifest.json').read_text(encoding='utf-8'))
    for filename, info in manifest['files'].items():
        if file_hash(source/filename) != info['sha256']:
            raise ValueError('source checksum mismatch')
    shards = []
    for item in manifest['shards']:
        path = cache/('miracl-ko-' + Path(item['path']).name)
        if file_hash(path) != item['lfs']['oid']:
            raise ValueError('corpus checksum mismatch')
        shards.append(path)

    def docs():
        for path in shards:
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                for line in stream:
                    yield json.loads(line)
    return select_miracl(
        (source/'topics.miracl-v1.0-ko-dev.tsv').read_text(encoding='utf-8'),
        (source/'qrels.miracl-v1.0-ko-dev.tsv').read_text(encoding='utf-8'), docs())


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    pool = rebuild(args.source, args.cache)
    with Path(args.out).open('x', encoding='utf-8') as stream:
        json.dump(pool, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
