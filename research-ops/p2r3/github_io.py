"""One-attempt GitHub operations for encrypted research transport.

Writes never update existing files or refs. A failed or ambiguous write is fatal;
callers must not retry claims or infer that a timeout means nothing was written.
"""
import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class GitHubIOError(RuntimeError):
    """Sanitized API failure; carries no remote response or credential."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def _path(value):
    if (not isinstance(value, str) or not value
            or any(part in ('', '.', '..') for part in value.split('/'))
            or not re.fullmatch(r'[A-Za-z0-9_./-]+', value)):
        raise GitHubIOError('InvalidPath')
    return urllib.parse.quote(value, safe='/')


class GitHubIO:
    def __init__(self, repo, branch, token, run_id, *, opener=None):
        if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise GitHubIOError('InvalidRepository')
        _path(branch)
        if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise GitHubIOError('InvalidCredential')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', str(run_id)):
            raise GitHubIOError('InvalidRun')
        self.repo, self.branch, self.run_id = repo, branch, str(run_id)
        self._token = token
        self._opener = opener if opener is not None else urllib.request.build_opener(
            urllib.request.ProxyHandler(), NoRedirect())

    def _request(self, method, suffix, payload=None, *, missing_ok=False):
        try:
            data = None if payload is None else json.dumps(payload, separators=(',', ':'), allow_nan=False).encode('utf-8')
            request = urllib.request.Request(
                'https://api.github.com/repos/' + self.repo + '/' + suffix,
                data=data, method=method, headers={
                    'Authorization': 'Bearer ' + self._token,
                    'Accept': 'application/vnd.github+json',
                    'Content-Type': 'application/json',
                    'X-GitHub-Api-Version': '2022-11-28',
                    'User-Agent': 'private-research-runner/' + self.run_id,
                })
            with self._opener.open(request, timeout=60) as response:
                expected = 200 if method == 'GET' else 201
                if response.status != expected:
                    raise GitHubIOError('UnexpectedHTTPStatus')
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise GitHubIOError('ResponseTooLarge')
                return json.loads(raw.decode('utf-8'))
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if missing_ok and method == 'GET' and code == 404:
                return None
            raise GitHubIOError('HTTPError:' + str(code)) from None
        except GitHubIOError:
            raise
        except Exception as exc:
            raise GitHubIOError(type(exc).__name__) from None

    def get_bytes(self, path):
        suffix = 'contents/' + _path(path) + '?ref=' + urllib.parse.quote(self.branch, safe='')
        item = self._request('GET', suffix, missing_ok=True)
        if item is None:
            return None
        try:
            if item['type'] != 'file' or item['encoding'] != 'base64':
                raise ValueError()
            # GitHub folds base64 into lines; no other whitespace is accepted.
            raw = base64.b64decode(item['content'].replace('\n', '').replace('\r', ''), validate=True)
            if item['sha'] != _blob_sha(raw) or type(item['size']) is not int or item['size'] != len(raw):
                raise ValueError()
            return raw
        except Exception:
            raise GitHubIOError('InvalidContent') from None

    def get_json(self, path):
        raw = self.get_bytes(path)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            raise GitHubIOError('InvalidJSON') from None

    def put_bytes(self, path, data, message):
        suffix = 'contents/' + _path(path)
        if not isinstance(data, bytes) or not isinstance(message, str):
            raise GitHubIOError('InvalidContent')
        result = self._request('PUT', suffix, {
            'message': message, 'content': base64.b64encode(data).decode('ascii'),
            'branch': self.branch,
        })
        expected = _blob_sha(data)
        if not isinstance(result, dict) or not isinstance(result.get('content'), dict) or result['content'].get('sha') != expected:
            raise GitHubIOError('InvalidWriteAcknowledgment')
        return expected

    def claim(self, family, commit_sha):
        if not isinstance(family, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', family):
            raise GitHubIOError('InvalidFamily')
        if not isinstance(commit_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', commit_sha):
            raise GitHubIOError('InvalidCommit')
        ref = 'refs/tags/research-lock/' + family
        result = self._request('POST', 'git/refs', {'ref': ref, 'sha': commit_sha})
        if (not isinstance(result, dict) or result.get('ref') != ref
                or not isinstance(result.get('object'), dict)
                or result['object'].get('sha') != commit_sha or result['object'].get('type') != 'commit'):
            raise GitHubIOError('InvalidClaimAcknowledgment')
        return commit_sha
