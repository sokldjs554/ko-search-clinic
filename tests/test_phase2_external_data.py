import pytest

from searchclinic.research.phase2.external_data import select_miracl


def test_selection_is_source_order_preserving_with_negative_judgments():
    docs = [{'docid':'D1','title':'제목','text':'본문'},
            {'docid':'D2','title':'다른 제목','text':'다른 본문'}]
    pool = select_miracl('9\t질문??\n2\t둘째\n1\t셋째\n',
        '9 Q0 D1 1\n9 Q0 D2 0\n2 Q0 D2 1\n1 Q0 D1 1\n', iter(docs), count=2)
    assert pool['topics'] == [['9','질문??'], ['2','둘째']]
    assert pool['judgments'] == {'9':{'D1':1,'D2':0},'2':{'D2':1}}
    assert pool['documents']['D1'] == docs[0]


@pytest.mark.parametrize('qrels', ['9 Q0 D1 2\n', '9 Q0 D1 1\n9 Q0 D1 0\n'])
def test_invalid_or_duplicate_judgments_rejected(qrels):
    with pytest.raises(ValueError, match='judgment'):
        select_miracl('9\t질문\n',qrels,iter([]),count=1)


def test_missing_documents_not_silently_dropped():
    with pytest.raises(ValueError, match='missing'):
        select_miracl('9\t질문\n','9 Q0 D1 1\n',iter([]),count=1)


def test_duplicate_queries_rejected_instead_of_replaced():
    with pytest.raises(ValueError, match='duplicate'):
        select_miracl('9\t질문\n2\t 질문 \n','',iter([]),count=2)
