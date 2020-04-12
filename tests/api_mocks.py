import functools
import json
import logging
import os
import random
import string
import sys

import pytest
from six import binary_type
from wandb.apis import InternalApi
import wandb.util
import yaml


def _files():
    return {
        'uploadHeaders': [],
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
    files = {'uploadHeaders': [], 'edges': []} if empty else (files or _files())
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
            'eventsTail': '[]',
            'config': '{"epochs": {"value": 20}}'
        }
    }


def _bucket(name='test', entity_name='bagsy', project_name='new-project'):
    return {
        'name': name,
        'description': "Description of the bucket",
        'framework': 'keras',
        'id': 'a1b2c3d4e5',
        'displayName': 'glorious-flowers-63',
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


def _project(name='test-projo'):
    return {
        'id': name,
        'name': name,
    }


def run_response(name='test'):
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
        'tags': [],
        'notes': None,
        'sweepName': None,
    }


def random_run_response():
    root = 'run-test-{}'.format(wandb.util.generate_id())
    name = '{}-name'.format(root)
    return {
        'id': '{}-id'.format(root),
        'name': name,
        'displayName': name,
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
        'tags': [],
        'notes': None,
        'sweepName': None,
    }


def random_sweep_response():
    root = 'sweep-test-{}'.format(wandb.util.generate_id())
    return {
        'id': '{}-id'.format(root),
        'name': '{}-name'.format(root),
        'bestLoss': 0.23,
        'config': yaml.dump({'method': 'random', 'parameters': {'lr': {'max': 0.1, 'min': 0.01}}}),
    }


def basic_report_response():
    spec = open(os.path.join(os.path.dirname(__file__), "fixtures/report.json")).read()
    return {
        'allViews': {
            'edges': [{
                'node': {
                    'name': "Test report",
                    'description': "Test",
                    'user': {
                        'name': 'vanpelt',
                        'photoUrl': 'http://vandev.com'
                    },
                    'spec': spec,
                    'updatedAt': 'today'
                },
                'cursor': 'rand'
            }]
        }
    }


def _run_files():
    return {
        'fileCount': 2,
        'id': 'abc123',
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


def mock_graphql_request(mocker, payload=None, error=None, body_match=None,
                         status_code=None, attempts=None):
    """Mock a sequence of graphql requests (retries) and their eventual response.

    Arguments:
        mocker: request_mocker fixture
        payload (nested dict/list): Response body to eventually return.
        error (nested dict/list): Error payload to return rather than `payload`.
        body_match (str = 'query'): A string to match in the request body that
            causes this mock to be used. This is important any time you're using
            more than one request mock at once. Otherwise, the last mock defined
            will determine what gets returned.
        status_code (int = 200): HTTP response status code to return on request
            attempts before the final one. The final attempt will always return
            200.
        attempts (int): Number of attempts to wait for before allowing the
            request to succeed or fail.
    """
    if error:
        body={'errors': error}
    else:
        body={'data': payload}
    if body_match is None:
        body_match='query'
    if status_code is None:
        status_code=200
    if attempts is None:
        attempts=1

    def match_body(request):
        return body_match in (request.text or '')

    res=[{'json': body, 'status_code': status_code}]
    if attempts > 1:
        for i in range(attempts - 1):
            if i == attempts - 2:
                status_code=200
            res.append({'json': body, 'status_code': status_code})
    return mocker.register_uri('POST', 'https://api.wandb.ai/graphql',
                               res, additional_matcher=match_body)


def graphql_request_mocker(payload=None, body_match=None):
    """Make a function to mock a query or mutation that returns a particular
    response after a certain number of retries.

    Arguments to this function and the function it returns match
    `mock_graphql_request()`.
    """
    @functools.wraps(mock_graphql_request)
    def wrapper(mocker, status_code=None, error=None, attempts=None):
        return mock_graphql_request(mocker, payload=payload,
                                    body_match=body_match, error=error, status_code=status_code,
                                    attempts=attempts)
    return wrapper


def query_mocker(key, json, body_match="query"):
    """Shorthand of `graphql_request_mocker()` for a single query."""
    payload={}
    if type(json) == list:
        json={'edges': [{'node': item} for item in json]}
    payload[key]=json
    return graphql_request_mocker(payload=payload, body_match=body_match)


def mutation_mocker(key, json):
    """Shorthand of `graphql_request_mocker()` for a single mutation."""
    payload={}
    payload[key]=json
    return graphql_request_mocker(payload=payload, body_match="mutation")


@pytest.fixture
def upsert_run(request, entity_name='bagsy', project_name='new-project'):
    return mutation_mocker('upsertBucket',
                           {'bucket': _bucket("default", entity_name=entity_name, project_name=project_name)})


@pytest.fixture
def query_project():
    # this should really be called query_download_urls
    return query_mocker('model', _download_urls(), body_match="updatedAt")


@pytest.fixture
def query_run_resume_status(request):
    return query_mocker('model', _run_resume_status(), body_match="historyTail")


@pytest.fixture
def query_no_run_resume_status():
    return query_mocker('model', {'bucket': None}, body_match="historyTail")


@pytest.fixture
def query_download_h5():
    def wrapper(mocker, status_code=200, error=None, content=None):
        mocker.register_uri('GET', 'https://h5py.url',
                            content=content, status_code=status_code)
        return query_mocker('model', _download_urls(files={'edges': [{'node': {
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
        return query_mocker('model', _download_urls(files={'uploadHeaders': [], 'edges': [{'node': {
            'name': 'wandb.h5',
            'url': 'https://h5py.url',
            'md5': 'fakemd5'
        }}]}), body_match='files(names: ')(mocker, status_code, error)
    return wrapper


@pytest.fixture
def query_empty_project():
    return query_mocker('model', _download_urls(empty=True))


@pytest.fixture
def query_projects():
    return query_mocker('models', [_download_urls("test_1"), _download_urls("test_2"), _download_urls("test_3")], body_match="query Models")


@pytest.fixture
def query_runs():
    return query_mocker('buckets', [_bucket("default"), _bucket("test_1")])


@pytest.fixture
def query_run(request_mocker):
    def wrapper(request_mocker, metadata={"docker": "test/docker", "program": "train.py", "args": ["--test", "foo"]}):
        request_mocker.register_uri('GET', 'https://metadata.json',
                                    content=json.dumps(metadata).encode('utf8'), status_code=200)
        return query_mocker('model', {'bucket': _bucket_config()})(request_mocker)
    return wrapper


@pytest.fixture
def query_run_v2():
    return query_mocker('project', {'run': run_response()}, body_match='run(name:')


@pytest.fixture
def query_run_files(request_mocker):
    request_mocker.register_uri('GET', "https://weights.url")
    return query_mocker('project', {'run': _run_files()},
                        body_match='files(names: ')


@pytest.fixture
def query_runs_v2():
    return query_mocker('project', {
        'runCount': 4,
        'runs': {
            'pageInfo': {
                'hasNextPage': True,
                'endCursor': 'end'
            },
            'edges': [{'node': run_response(),
                       'cursor': 'cursor'}, {'node': run_response(),
                                             'cursor': 'cursor'}]
        }
    })


@pytest.fixture
def query_projects_v2():
    return query_mocker('models', {
        'pageInfo': {
            'hasNextPage': False,
            'endCursor': 'end'
        },
        'edges': [{'node': _project('p1'),
                   'cursor': 'cursor'},
                  {'node': _project('p2'),
                   'cursor': 'cursor'}]
    })


@pytest.fixture
def query_viewer(request):
    marker = request.node.get_closest_marker('teams')
    if marker:
        teams = marker.args
    else:
        teams = ['foo']
    return graphql_request_mocker(payload={'viewer': {
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
