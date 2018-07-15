import pytest
import os
from six import binary_type
import logging


def _files():
    return {
        'edges': [
            {'node': {
                'name': 'weights.h5',
                'url': 'https://weights.url',
                'md5': 'fakemd5',
                'updatedAt': None
            }},
            {'node': {
                'name': 'model.json',
                'url': 'https://model.url',
                'md5': 'mZFLkyvTelC5g8XnyQrpOw==',
                'updatedAt': None
            }},
        ]
    }


def _download_urls(name='test', empty=False, files=None):
    files = {'edges': []} if empty else (files or _files())
    return {
        'name': name,
        'description': 'Test model',
        'bucket': {
            'id': 'test1234',
            'framework': 'keras',
            'files': files
        }
    }


def _run_resume_status(name='test', empty=False, files=None):
    return {
        'bucket': {
            'name': name,
            'id': name,
            'logLineCount': 14,
            'historyLineCount': 5,
            'eventsLineCount': 2,
            'historyTail': '[]',
            'eventsTail': '[]'
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


def _run(name='test'):
    return {
        'id': 'test',
        'name': name,
        'state': "running",
        'config': '{"epochs": {"value": 10}}',
        'systemMetrics': '{"cpu": 100}',
        'summaryMetrics': '{"acc": 100, "loss": 0}',
        'history': [
            '{"acc": 10, "loss": 90}',
            '{"acc": 20, "loss": 80}',
            '{"acc": 30, "loss": 70}'
        ],
        'events': [
            '{"cpu": 10}',
            '{"cpu": 20}',
            '{"cpu": 30}'
        ]
    }


def _bucket_config():
    return {
        'patch': '''
diff --git a/patch.txt b/patch.txt
index 30d74d2..9a2c773 100644
--- a/patch.txt
+++ b/patch.txt
@@ -1 +1 @@
-test
\ No newline at end of file
+testing
\ No newline at end of file
        ''',
        'commit': 'HEAD',
        'config': '{"foo":{"value":"bar"}}'
    }


def success_or_failure(payload=None, body_match="query"):
    def wrapper(mocker, status_code=200, error=None):
        if error:
            body = {'errors': error}
        else:
            body = {'data': payload}

        def match_body(request):
            return body_match in (request.text or '')

        return mocker.register_uri('POST', 'https://api.wandb.ai/graphql',
                                   [{'json': body, 'status_code': status_code}], additional_matcher=match_body)
    return wrapper


def _query(key, json, body_match="query"):
    payload = {}
    if type(json) == list:
        json = {'edges': [{'node': item} for item in json]}
    payload[key] = json
    return success_or_failure(payload=payload, body_match=body_match)


def _mutate(key, json):
    payload = {}
    payload[key] = json
    return success_or_failure(payload=payload, body_match="mutation")


@pytest.fixture
def upsert_run(request):
    updateAvailable = True if request.node.get_marker(
        'updateAvailable') else False
    return _mutate('upsertBucket', {'bucket': _bucket("default"), 'updateAvailable': updateAvailable})


@pytest.fixture
def query_project():
    # this should really be called query_download_urls
    return _query('model', _download_urls(), body_match="updatedAt")


@pytest.fixture
def query_run_resume_status(request):
    return _query('model', _run_resume_status(), body_match="historyTail")


@pytest.fixture
def query_no_run_resume_status():
    return _query('model', {'bucket': None}, body_match="historyTail")


@pytest.fixture
def query_download_h5():
    def wrapper(mocker, status_code=200, error=None, content=None):
        mocker.register_uri('GET', 'https://h5py.url',
                            content=content, status_code=status_code)
        return _query('model', _download_urls(files={'edges': [{'node': {
            'name': 'wandb.h5',
            'url': 'https://h5py.url',
            'md5': 'fakemd5',
            'updatedAt': 'now',
        }}]}), body_match="files(names: [")(mocker, status_code, error)

    return wrapper


@pytest.fixture
def query_upload_h5(mocker):
    def wrapper(mocker, status_code=200, error=None, content=None):
        mocker.register_uri('PUT', "https://h5py.url")
        return _query('model', _download_urls(files={'edges': [{'node': {
            'name': 'wandb.h5',
            'url': 'https://h5py.url',
            'md5': 'fakemd5'
        }}]}), body_match='files(names: ')(mocker, status_code, error)
    return wrapper


@pytest.fixture
def query_empty_project():
    return _query('model', _download_urls(empty=True))


@pytest.fixture
def query_projects():
    return _query('models', [_download_urls("test_1"), _download_urls("test_2"), _download_urls("test_3")], body_match="query Models")


@pytest.fixture
def query_runs():
    return _query('buckets', [_bucket("default"), _bucket("test_1")])


@pytest.fixture
def query_run():
    return _query('model', {'bucket': _bucket_config()})


@pytest.fixture
def query_run_v2():
    return _query('project', {'run': _run()})


@pytest.fixture
def query_runs_v2():
    return _query('project', {
        'runCount': 4,
        'runs': {
            'pageInfo': {
                'hasNextPage': True,
                'endCursor': 'end'
            },
            'edges': [{'node': _run(),
                       'cursor': 'cursor'}, {'node': _run(),
                                             'cursor': 'cursor'}]
        }
    })


@pytest.fixture
def query_viewer(request):
    marker = request.node.get_marker('teams')
    if marker:
        teams = marker.args
    else:
        teams = ['foo']
    return success_or_failure(payload={'viewer': {
        'entity': 'foo',
        'teams': {
            'edges': [{'node': {'name': team}} for team in teams]
        }
    }}, body_match="query Viewer")


@pytest.fixture
def upload_url():
    def wrapper(mocker, status_code=200, headers={}):
        mocker.register_uri('PUT', 'https://weights.url',
                            status_code=status_code, headers=headers)
        mocker.register_uri('PUT', 'https://model.url',
                            status_code=status_code, headers=headers)
    return wrapper


@pytest.fixture
def download_url():
    def wrapper(mocker, status_code=200, error=None, size=5000):
        mocker.register_uri('GET', 'https://weights.url',
                            content=os.urandom(size), status_code=status_code)
        mocker.register_uri('GET', 'https://model.url',
                            content=os.urandom(size), status_code=status_code)
    return wrapper


@pytest.fixture
def upload_logs():
    def wrapper(mocker, run, status_code=200, body_match='', error=None):
        from wandb.cli import api

        def match_body(request):
            return body_match in (request.text or '')

        api._current_run_id = run
        url = api.get_file_stream_api()._endpoint
        return mocker.register_uri("POST", url,
                                   status_code=status_code, additional_matcher=match_body)
    return wrapper
