import json
import os
import subprocess
from unittest.mock import MagicMock

import kubernetes
import wandb
import wandb.sdk.launch.launch as launch
import pytest
from tests import utils

from .test_launch import mocked_fetchable_git_repo, mock_load_backend  # noqa: F401


class MockDict(dict):
    # use a dict to mock an object
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


class MockPodList(object):
        def __init__(self, pods):
            self.pods = pods
        @property
        def items(self):
            return self.pods

class MockBatchV1Api(object):
    def __init__(self, mock_api_client, jobs):
        self.context = mock_api_client['context_name']
        self.jobs = jobs

    def read_namespaced_job(self, name, namespace):
        return self.jobs[name]

    def read_namespaced_job_status(self, name, namespace):
        return self.jobs[name]

    def patch_namespaced_job(self, name, namespace, body):
        if body.spec.suspend:
            self.jobs[name].status.conditions = [MockDict({'type': 'Suspended'})]

    def delete_namespaced_job(self, name, namespace):
        del self.jobs[name]


class MockCoreV1Api(object):
    def __init__(self, mock_api_client, pods):
        self.context = mock_api_client['context_name']
        self.pods = pods
    
    def list_namespaced_pod(self, label_selector, namespace):
        ret = []
        k, v = label_selector.split('=')
        if k == 'job-name':
            for pod in self.pods.items:
                if pod.job_name == v:
                    ret.append(pod)
        return MockPodList(ret)

    def read_namespaced_pod_log(self, name, namespace):
        for pod in self.pods.items:
            if pod.metadata.name == name:
                return pod.log


def setup_mock_kubernetes_client(monkeypatch, jobs, pods, mock_job):
    mock_contexts = [
        {'name': 'active-context', 'context': {'namespace': 'active-namespace'}},
        {'name': 'inactive-context', 'context': {'namespace': 'inactive-namespace'}},
    ]

    def mock_api_config(context):
        return {
            'context_name': context,
        }

    def mock_create_from_yaml(api_client, yaml_objects, namespace, jobs_dict, mock_job):
        jobd = yaml_objects[0]
        name = jobd['metadata']['name']
        if not name:
            name = jobd['metadata']['generateName'] + 'asdfasdf'
        jobs_dict[name] = mock_job
        return [[mock_job]]

    monkeypatch.setattr(
        kubernetes.config,
        'list_kube_config_contexts',
        lambda config_file: (mock_contexts, mock_contexts[0])
    )
    monkeypatch.setattr(
        kubernetes.config,
        'new_client_from_config',
        lambda config_file, context: mock_api_config(context)
    )
    monkeypatch.setattr(kubernetes.config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes.client.api_client, 'ApiClient', lambda: mock_api_config(None))
    monkeypatch.setattr(kubernetes.config, 'load_kube_config', lambda config_file, context_name: None)
    monkeypatch.setattr(
        kubernetes.client,
        'BatchV1Api',
        lambda api_client: MockBatchV1Api(api_client, jobs)
    )
    monkeypatch.setattr(
        kubernetes.client,
        'CoreV1Api',
        lambda api_client: MockCoreV1Api(api_client, pods)
    )
    monkeypatch.setattr(
        kubernetes.utils,
        "create_from_yaml",
        lambda api_client, yaml_objects, namespace: mock_create_from_yaml(api_client, yaml_objects, namespace, jobs, mock_job)
    )


def pods(job_name):
    return MockPodList([
            MockDict({
                'metadata': MockDict({
                    'name': 'pod1',
                }),
                'job_name': job_name,
                'log': 'test log string',
            })
        ])

# 'conditions': [MockDict({'type': 'Suspended'})],

@pytest.mark.timeout(320)
def test_launch_kube(live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch):
    jobs = {}
    job = MockDict({
        'status': MockDict({
            'succeeded': 1,
            'failed': 0,
            'active': 0,
            'conditions': None,
        }),
        'spec': MockDict({
            'suspend': False,
        }),
        'metadata': MockDict({
            'name': 'test-job',
            'labels': {
                'job-name': 'test-job'
            }
        })
    })

    setup_mock_kubernetes_client(monkeypatch, jobs, pods('test-job'), job)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "kubernetes",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {
            "kubernetes": {
                'job_name': 'test-job',
            },
        },
    }
    run = launch.run(**kwargs)

    assert run.id == 'test-job'
    assert run.namespace == 'active-namespace'
    assert run.pod_names == ['pod1']
    assert run.get_status().state == "finished"
    assert run.wait()


@pytest.mark.timeout(320)
def test_launch_kube_suspend_cancel(live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch):
    jobs = {}
    job = MockDict({
        'status': MockDict({
            'succeeded': 0,
            'failed': 0,
            'active': 0,
            'conditions': None,
        }),
        'spec': MockDict({
            'suspend': False,
        }),
        'metadata': MockDict({
            'name': None,
            'labels': {
                'job-name': 'launch-asdfasdf'
            }
        })
    })

    setup_mock_kubernetes_client(monkeypatch, jobs, pods('launch-asdfasdf'), job)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "kubernetes",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {
            "kubernetes": {
            },
        },
    }
    run = launch.run(**kwargs)
    run.suspend()

    assert run.id == 'launch-asdfasdf'
    assert run.namespace == 'active-namespace'
    assert run.pod_names == ['pod1']
    assert run.get_status().state == 'stopped'

    run.cancel()

    with pytest.raises(KeyError):
        run.get_status()


