import pytest, os
from six import binary_type

def _files():
    return {
        'edges': [
            {'node': {
                'name': 'weights.h5',
                'url': 'https://weights.url',
                'md5': 'fakemd5'
            }},
            {'node': {
                'name': 'model.json',
                'url': 'https://model.url',
                'md5': 'mZFLkyvTelC5g8XnyQrpOw=='
            }},
        ]
    }

def project(name='test', empty=False, files=None):
    files = {'edges':[]} if empty else (files or _files())
    return {
        'name': name,
        'description': 'Test model',
        'bucket': {
            'id': 'test1234',
            'framework': 'keras',
            'files': files
        }
    }

def _bucket(name='test'):
    return {
        'name': name,
        'description': "Description of the bucket",
        'framework': 'keras',
        'id': 'a1b2c3d4e5',
        'files': _files()
    }

def success_or_failure(payload=None, body_match="query"):
    def wrapper(mocker, status_code=200, error=None):
        if error:
            body = {'error': error}
        else:
            body = {'data': payload}

        def match_body(request):
            return body_match in (request.text or '')

        return mocker.register_uri('POST', 'https://api.wandb.ai/graphql', 
            json=body, status_code=status_code, additional_matcher=match_body)
    return wrapper

def _query(key, json):
    payload = {}
    if type(json) == list:
        json = {'edges': [{'node': item} for item in json]}
    payload[key] = json
    return success_or_failure(payload=payload)

def _mutate(key, json):
    payload = {}
    payload[key]=json
    return success_or_failure(payload=payload, body_match="mutation")

@pytest.fixture
def update_bucket():
    return _mutate('upsertBucket', {'bucket': _bucket("default")})

@pytest.fixture
def query_project():
    return _query('model', project())

@pytest.fixture
def query_empty_project():
    return _query('model', project(empty=True))

@pytest.fixture
def query_projects():
    return _query('models', [project("test_1"), project("test_2"), project("test_3")])

@pytest.fixture
def query_buckets():
    return _query('buckets', [_bucket("default"), _bucket("test_1")])

@pytest.fixture
def query_viewer():
    return success_or_failure(payload={'viewer': {'entity': 'foo'}})

@pytest.fixture
def upload_url():
    def wrapper(mocker, status_code=200, headers={}):
        mocker.register_uri('PUT', 'https://weights.url', status_code=status_code, headers=headers)
        mocker.register_uri('PUT', 'https://model.url', status_code=status_code, headers=headers)
    return wrapper

@pytest.fixture
def download_url():
    def wrapper(mocker, status_code=200, error=None, size=5000):
        mocker.register_uri('GET', 'https://weights.url', 
            content=os.urandom(size), status_code=status_code)
        mocker.register_uri('GET', 'https://model.url', 
            content=os.urandom(size), status_code=status_code)
    return wrapper
