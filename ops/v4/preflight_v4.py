"""One fixed-model GET; no generation, credential persistence or retries."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

MODEL = 'gpt-4.1-mini-2025-04-14'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def check_model(key, opener=None):
    result = dict(model=MODEL, model_get_requests=0, generation_requests=0,
                  access='missing_secret')
    if not key:
        return result
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(), NoRedirect()).open
    request = urllib.request.Request('https://api.openai.com/v1/models/' + MODEL,
        headers={'Authorization': 'Bearer ' + key})
    result['model_get_requests'] = 1
    try:
        with opener(request, timeout=30) as response:
            raw = response.read(100001)
            if len(raw) > 100000 or response.status != 200:
                result['access'] = 'invalid_response'
            else:
                result['access'] = 'confirmed' if json.loads(raw).get('id') == MODEL else 'model_mismatch'
    except urllib.error.HTTPError as error:
        result['access'] = 'http_' + str(error.code)
        error.close()
    except Exception as error:
        result['access'] = 'unconfirmed_' + type(error).__name__
    return result

def main():
    result = check_model(os.environ.get('OPENAI_API_KEY', ''))
    result.update(workflow_sha=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'],
                  repository=os.environ['GITHUB_REPOSITORY'], run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    output = Path(os.environ['RUNNER_TEMP']) / 'v4-model-access.json'
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['access'] == 'confirmed' else 1

if __name__ == '__main__':
    raise SystemExit(main())
