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

def _project(name='test', empty=False):
    files = {'edges':[]} if empty else _files()
    return {
        'name': name,
        'description': 'Test model',
        'bucket': {
            'framework': 'keras',
            'files': files
        }
    }

def _buckets(name='test'):
    return {
        'name': name,
        'description': "Description of the tag",
        'framework': 'keras',
        'files': _files()
    }

def _success_or_failure(payload=None):
    def wrapper(mocker, status_code=200, error=None):
        if error:
            body = {'error': error}
        else:
            body = {'data': payload}

        mocker.register_uri('POST', 'https://api.wandb.ai/graphql', 
            json=body, status_code=status_code)
    return wrapper

def _query(key, json):
    payload = {}
    if type(json) == list:
        json = {'edges': [{'node': item} for item in json]}
    payload[key] = json
    return _success_or_failure(payload=payload)

def _mutate(key, json):
    payload = {}
    payload[key]=json
    return _success_or_failure(payload=payload)

@pytest.fixture
def query_project():
    return _query('model', _project())

@pytest.fixture
def query_empty_project():
    return _query('model', _project(empty=True))

@pytest.fixture
def query_projects():
    return _query('models', [_project("test_1"), _project("test_2"), _project("test_3")])

@pytest.fixture
def query_buckets():
    return _query('buckets', [_bucket("default"), _bucket("test_1")])

@pytest.fixture
def query_viewer():
    return _success_or_failure(payload={'viewer': {'entity': 'foo'}})

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
