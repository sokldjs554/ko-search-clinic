import json
import httpx
import pytest
from searchclinic.rag.openai_provider import OpenAIExplainer, Budget, ProviderError

def response(output='{}', status='completed'):
    return {'id':'resp_test','model':'gpt-5.4-mini-2026-03-17','status':status,
        'output':[{'type':'message','content':[{'type':'output_text','text':output}]}],
        'usage':{'input_tokens':100, 'output_tokens':50,
                 'input_tokens_details':{'cached_tokens':0}, 'output_tokens_details':{'reasoning_tokens':0}}}

def test_request_is_structured_bounded_and_does_not_store_data():
    def handler(request):
        body = json.loads(request.content)
        assert body['store'] is False
        assert body['max_output_tokens'] == 800
        assert body['text']['format']['strict'] is True
        assert 'qrels' not in str(body)
        return httpx.Response(200,json=response('{"status":"abstain"}'))
    provider = OpenAIExplainer('test-key', client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.generate({'query':'후라이팬','documents':[]})
    assert result['raw'] == {'status':'abstain'}
    assert result['usage']['input_tokens'] == 100
    assert result['estimated_usd'] == pytest.approx(.0003)

@pytest.mark.parametrize('status', [401,429,500])
def test_http_failure_is_redacted_and_charged_without_retry(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET must not be reflected')
    budget = Budget(max_calls=1)
    provider = OpenAIExplainer('test-key', budget=budget, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError, match='upstream_http') as exc:
        provider.generate({'query':'후라이팬'})
    assert 'SECRET' not in str(exc.value)
    with pytest.raises(ProviderError, match='budget_exhausted'):
        provider.generate({'query':'후라이팬'})
    assert len(calls) == 1

@pytest.mark.parametrize('payload', [response(status='incomplete'), response('not JSON'),
    {'status':'completed','output':[], 'usage':{}}])
def test_incomplete_or_malformed_output_is_not_success(payload):
    provider = OpenAIExplainer('test-key', client=httpx.Client(transport=httpx.MockTransport(
        lambda r:httpx.Response(200,json=payload))))
    with pytest.raises(ProviderError):
        provider.generate({'query':'후라이팬'})

def test_oversized_request_does_not_consume_budget_or_call_provider():
    budget = Budget()
    provider = OpenAIExplainer('test-key',budget=budget)
    with pytest.raises(ProviderError,match='input_too_large'):
        provider.generate({'query':'가'*20000})
    assert budget.calls == 0

def test_budget_reservation_survives_reload(tmp_path):
    path=tmp_path/'budget.json'
    Budget(path=path,max_calls=1).reserve()
    with pytest.raises(ProviderError,match='budget_exhausted'):
        Budget(path=path,max_calls=1).reserve()
