import pytest
from fastapi.testclient import TestClient
from searchclinic.api.explanation_api import create_explanation_app
from searchclinic.rag.openai_provider import ProviderError

@pytest.fixture(scope='module')
def client(): return TestClient(create_explanation_app())

def test_default_app_cannot_spend_money(client):
    assert client.post('/explanations',json={'query':'후라이팬','problem':'표기 변형'}).status_code == 503

def test_demo_and_status_distinguish_disabled_generation(client):
    assert client.get('/demo/').status_code == 200
    status=client.get('/explanation-status').json()
    assert status['live_enabled'] is False
    assert status['metrics']['requests'] == 0

class FailingProvider:
    def generate(self, context): raise ProviderError('upstream_timeout')

@pytest.fixture(scope='module')
def live(): return TestClient(create_explanation_app(provider=FailingProvider(),token='x'*24))

def test_unauthorized_request_cannot_reach_paid_provider(live):
    assert live.post('/explanations',json={'query':'후라이팬'}).status_code == 401

def test_failure_returns_safe_error_and_operational_counter(live):
    response=live.post('/explanations',json={'query':'후라이팬'},headers={'Authorization':'Bearer '+'x'*24})
    assert response.status_code == 502
    assert response.json()['detail'] == 'upstream_timeout'
    stats=live.get('/explanation-status').json()['metrics']
    assert stats['upstream_errors'] == 1
    assert stats['requests'] == 1

@pytest.mark.parametrize('query',['',' '*5,'가'*101])
def test_input_limits_before_model_call(live,query):
    assert live.post('/explanations',json={'query':query},headers={'Authorization':'Bearer '+'x'*24}).status_code == 422
