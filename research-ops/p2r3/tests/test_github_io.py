import base64
import hashlib
import importlib
import io
import json
import traceback
import urllib.error

import pytest


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(json.dumps(value).encode())
        self.status = status


class Server:
    def __init__(self):
        self.requests = []
        self.files = {}
        self.refs = {}
        self.timeout_after_claim = False
        self.failure = None

    def open(self, request, timeout):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        method = request.get_method()
        path = request.full_url.split('/repos/owner/repo/', 1)[1].split('?', 1)[0]
        value = json.loads(request.data) if request.data else None
        if method == 'GET':
            if path not in self.files:
                raise urllib.error.HTTPError(request.full_url, 404, 'private-canary', {}, None)
            return Response(self.files[path])
        if method == 'PUT':
            if path in self.files:
                raise urllib.error.HTTPError(request.full_url, 422, 'private-canary', {}, None)
            assert 'sha' not in value
            data = base64.b64decode(value['content'])
            self.files[path] = dict(type='file', encoding='base64', content=value['content'], sha=blob_sha(data), size=len(data))
            return Response({'content': {'sha': blob_sha(data)}}, 201)
        if method == 'POST':
            if value['ref'] in self.refs:
                raise urllib.error.HTTPError(request.full_url, 422, 'private-canary', {}, None)
            self.refs[value['ref']] = value['sha']
            if self.timeout_after_claim:
                raise TimeoutError('private-canary')
            return Response({'ref': value['ref'], 'object': {'sha': value['sha'], 'type': 'commit'}}, 201)
        raise AssertionError(method)


@pytest.fixture
def adapter():
    # Import in fixture so initial red reports the missing feature per test.
    module = importlib.import_module('github_io')
    server = Server()
    return module, server, module.GitHubIO('owner/repo', 'ops/private', 'secret-canary', '123', opener=server)


def test_read_missing_and_roundtrip_content_with_real_requests(adapter):
    _, server, client = adapter
    assert client.get_json('run/data.json') is None
    content = b'{"ok": true}'
    assert client.put_bytes('run/data.json', content, 'encrypted checkpoint') == blob_sha(content)
    assert client.get_bytes('run/data.json') == content
    assert client.get_json('run/data.json') == {'ok': True}
    request = server.requests[-1]
    assert request.full_url == 'https://api.github.com/repos/owner/repo/contents/run/data.json?ref=ops%2Fprivate'
    assert request.get_header('Authorization') == 'Bearer secret-canary'


def test_existing_content_cannot_be_replaced(adapter):
    module, server, client = adapter
    client.put_bytes('run/data', b'first', 'checkpoint')
    with pytest.raises(module.GitHubIOError):
        client.put_bytes('run/data', b'second', 'checkpoint')
    assert client.get_bytes('run/data') == b'first'
    assert [r.get_method() for r in server.requests] == ['PUT', 'PUT', 'GET']


def test_claim_is_atomic_and_not_repeated_after_ambiguous_success(adapter):
    module, server, client = adapter
    server.timeout_after_claim = True
    with pytest.raises(module.GitHubIOError):
        client.claim('p2r3-gpt-fixed', 'a' * 40)
    assert len(server.requests) == 1
    assert server.refs == {'refs/tags/research-lock/p2r3-gpt-fixed': 'a' * 40}
    other = module.GitHubIO('owner/repo', 'other-branch', 'secret-canary', '456', opener=server)
    with pytest.raises(module.GitHubIOError):
        other.claim('p2r3-gpt-fixed', 'a' * 40)
    assert len(server.requests) == 2


def test_claim_success_requires_exact_ref_and_commit(adapter):
    _, _, client = adapter
    assert client.claim('p2r3-gpt-fixed', 'a' * 40) == 'a' * 40


@pytest.mark.parametrize('field,value', [('ref', 'refs/tags/other'), ('object', {'sha': 'b' * 40, 'type': 'commit'})])
def test_claim_rejects_mismatched_acknowledgment(adapter, field, value):
    module, server, client = adapter
    original = server.open
    def altered(request, timeout):
        response = json.load(original(request, timeout))
        response[field] = value
        return Response(response, 201)
    server.open = altered
    with pytest.raises(module.GitHubIOError):
        client.claim('p2r3-gpt-fixed', 'a' * 40)
    assert len(server.requests) == 1


@pytest.mark.parametrize('field,value', [('sha', '0' * 40), ('content', '!!!!'), ('size', 500), ('type', 'symlink')])
def test_read_rejects_corrupted_content(adapter, field, value):
    module, server, client = adapter
    client.put_bytes('run/data', b'ciphertext', 'checkpoint')
    server.files['contents/run/data'][field] = value
    with pytest.raises(module.GitHubIOError):
        client.get_bytes('run/data')


@pytest.mark.parametrize('failure', [TimeoutError('private-canary secret-canary'), urllib.error.HTTPError('https://evil/private-canary', 429, 'secret-canary', {}, io.BytesIO(b'private-canary'))])
def test_errors_do_not_expose_private_data_or_retry(adapter, failure):
    module, server, client = adapter
    server.failure = failure
    private_data = b'private-canary'
    with pytest.raises(module.GitHubIOError) as caught:
        client.put_bytes('run/data', private_data, 'checkpoint')
    rendered = ''.join(traceback.format_exception(caught.value))
    assert 'private-canary' not in rendered and 'secret-canary' not in rendered
    assert len(server.requests) == 1


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'a/../b', 'a//b', 'https://evil/a', 'a?x', 'a\\b'])
def test_invalid_paths_fail_before_network(adapter, path):
    module, server, client = adapter
    with pytest.raises(module.GitHubIOError):
        client.get_bytes(path)
    assert server.requests == []


def test_redirect_is_never_followed():
    module = importlib.import_module('github_io')
    assert module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil') is None
