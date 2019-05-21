import pytest
import os
import sys
import json
from six import binary_type
import logging
from wandb.apis import InternalApi


def _files():
    return {
        'edges': [
            {'node': {
                'name': 'weights.h5',
                'url': 'https://weights.url',
                'md5': 'fakemd5',
                'sizeBytes': "100",
                'mimetype': "",
                'updatedAt': None
            }},
            {'node': {
                'name': 'model.json',
                'url': 'https://model.url',
                'md5': 'mZFLkyvTelC5g8XnyQrpOw==',
                'sizeBytes': "1000",
                'mimetype': "application/json",
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
            'displayName': 'funky-town-13',
            'id': name,
            'summaryMetrics': '{"acc": 10}',
            'logLineCount': 14,
            'historyLineCount': 15,
            'eventsLineCount': 0,
            'historyTail': '["{\\"_step\\": 15, \\"acc\\": 1}"]',
            'eventsTail': '[]'
        }
    }


def _bucket(name='test', entity_name='bagsy', project_name='new-project'):
    return {
        'name': name,
        'description': "Description of the bucket",
        'framework': 'keras',
        'id': 'a1b2c3d4e5',
        'files': _files(),
        'project': {
            'id': '14',
            'name': project_name,
            'entity': {
                'id': '9',
                'name': entity_name
            }
        }
    }


def _run(name='test'):
    return {
        'id': 'test',
        'name': name,
        'displayName': 'beast-bug-33',
        'state': "running",
        'config': '{"epochs": {"value": 10}}',
        'description': "",
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
        ],
        'tags': []
    }


def _run_files():
    return {
        'fileCount': 2,
        'files': _files()
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
        'github': 'https://github.com/vanpelt',
        'config': '{"foo":{"value":"bar"}}',
        'files': {
            'edges': [{'node': {'url': 'https://metadata.json'}}]
        }
    }


def success_or_failure(payload=None, body_match="query"):
    def wrapper(mocker, status_code=200, error=None, attempts=1):
        """attempts will pass the status_code provided until the final attempt when it will pass 200"""
        if error:
            body = {'errors': error}
        else:
            body = {'data': payload}

        def match_body(request):
            return body_match in (request.text or '')

        res = [{'json': body, 'status_code': status_code}]
        if attempts > 1:
            for i in range(attempts - 1):
                if i == attempts - 2:
                    status_code = 200
                res.append({'json': body, 'status_code': status_code})
        return mocker.register_uri('POST', 'https://api.wandb.ai/graphql',
                                   res, additional_matcher=match_body)
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
def upsert_run(request, entity_name='bagsy', project_name='new-project'):
    return _mutate('upsertBucket',
                   {'bucket': _bucket("default", entity_name=entity_name, project_name=project_name)})


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
def query_run(request_mocker):
    def wrapper(request_mocker, metadata={"docker": "test/docker", "program": "train.py", "args": ["--test", "foo"]}):
        request_mocker.register_uri('GET', 'https://metadata.json',
                                    content=json.dumps(metadata).encode('utf8'), status_code=200)
        return _query('model', {'bucket': _bucket_config()})(request_mocker)
    return wrapper


@pytest.fixture
def query_run_v2():
    return _query('project', {'run': _run()}, body_match='run(name:')


@pytest.fixture
def query_run_files(request_mocker):
    request_mocker.register_uri('GET', "https://weights.url")
    return _query('project', {'run': _run_files()},
                  body_match='files(names: ')


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
    marker = request.node.get_closest_marker('teams')
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
        api = InternalApi()
        api.set_setting("project", "new-project")
        api.set_setting("entity", "bagsy")

        def match_body(request):
            return body_match in (request.text or '')

        api._current_run_id = run
        url = api.get_file_stream_api()._endpoint
        print("Mocked %s" % url)
        return mocker.register_uri("POST", url, [{'json': {'limits': {}}, 'status_code': status_code}],
                                   additional_matcher=match_body)
    return wrapper
