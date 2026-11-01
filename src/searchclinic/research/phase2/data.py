"""Expose leakage risk; exact lexical checks cannot certify semantics."""
from searchclinic.research.splits import normalize_query


def audit_overlap(dev, test):
    overlaps=[]
    dimensions={'normalized_query':lambda r:[normalize_query(r['query'])],
        'document_text':lambda r:[normalize_query(r['document_text'])],
        'synonym_term':lambda r:[normalize_query(x) for x in r['synonym_terms']],
        'template':lambda r:[r['template']], 'concept':lambda r:[r['concept']]}
    for dimension, values in dimensions.items():
        dev_values={v:r['query_id'] for r in dev for v in values(r) if v}
        for row in test:
            for value in values(row):
                if value in dev_values:
                    overlaps.append({'dimension':dimension,'test_query_id':row['query_id'],
                        'dev_query_id':dev_values[value],'value':value})
    return {'overlaps':overlaps,'semantic_review':'required',
            'independence_certified':False,
            'limitation':'Author-assigned IDs and exact strings do not detect all semantic or template leakage.'}
