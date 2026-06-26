import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.runner.kubernetes_monitor import LaunchKubernetesMonitor


class MockDict(dict):
    # use a dict to mock an object
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self.items():
            if isinstance(v, dict):
                self[k] = MockDict(v)
            elif isinstance(v, list):
                self[k] = [MockDict(i) if isinstance(i, dict) else i for i in v]


class MockEventStream:
    """Mocks a kubernetes event stream that can be populated from tests."""

    def __init__(self):
        self.queue = []

    async def __aiter__(self):
        while True:
            while not self.queue:
                await asyncio.sleep(0)
            yield self.queue.pop(0)

    async def add(self, event: Any):
        self.queue.append(event)


class MockBatchApi:
    """Mocks a kubernetes batch API client."""

    def __init__(self):
        self.jobs = dict()

    async def read_namespaced_job(self, name, namespace):
        return self.jobs[name]

    async def read_namespaced_job_status(self, name, namespace):
        return self.jobs[name]

    async def patch_namespaced_job(self, name, namespace, body):
        if body.spec.suspend:
            self.jobs[name].status.conditions = [MockDict({"type": "Suspended"})]
            self.jobs[name].status.active -= 1

    async def delete_namespaced_job(self, name, namespace):
        del self.jobs[name]

    async def list_namespaced_job(self, namespace, field_selector=None):
        return [self.jobs[name] for name in self.jobs]

    async def create_job(self, body):
        self.jobs[body["metadata"]["generateName"]] = body
        return body


@pytest.fixture
def clean_monitor():
    """Fixture for cleaning up the monitor class between tests."""
    LaunchKubernetesMonitor._instance = None
    yield
    LaunchKubernetesMonitor._instance = None


@pytest.fixture
def clean_agent():
    LaunchAgent._instance = None
    yield
    LaunchAgent._instance = None


@pytest.fixture
def manifest():
    return {
        "kind": "Job",
        "spec": {
            "template": {
                "metadata": {
                    "labels": {
                        "app": "wandb",
                    }
                },
                "spec": {
                    "containers": [
                        {
                            "name": "master",
                            "image": "${image_uri}",
                            "imagePullPolicy": "IfNotPresent",
                            "env": [
                                {"name": "MY_ENV_VAR", "value": "MY_VALUE"},
                            ],
                        },
                        {
                            "name": "worker",
                            "image": "${image_uri}",
                            "workingDir": "/home",
                            "imagePullPolicy": "IfNotPresent",
                        },
                    ],
                    "restartPolicy": "OnFailure",
                },
            }
        },
    }


@pytest.fixture
def mock_event_streams(monkeypatch):
    """Patches the kubernetes event stream with a mock and returns it."""
    job_stream = MockEventStream()
    pod_stream = MockEventStream()

    def _select_stream(_, api_call, *args, **kwargs):
        if api_call.__name__ == "list_namespaced_pod":
            return pod_stream
        elif api_call.__name__ == "list_namespaced_job":
            return job_stream
        elif api_call.__name__ == "list_namespaced_custom_object":
            return job_stream
        raise Exception(
            f"Event stream requested for unsupported API call: {api_call.__name__} "
        )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_monitor.SafeWatch.stream",
        _select_stream,
    )
    return job_stream, pod_stream


@pytest.fixture
def mock_batch_api(monkeypatch):
    """Patches the kubernetes batch api with a mock and returns it."""
    batch_api = MockBatchApi()
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.client.BatchV1Api",
        lambda *args, **kwargs: batch_api,
    )
    return batch_api


@pytest.fixture
def mock_kube_context_and_api_client(monkeypatch):
    """Patches the kubernetes context and api client with a mock and returns it."""

    async def _mock_get_kube_context_and_api_client(*args, **kwargs):
        return (None, None)

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.get_kube_context_and_api_client",
        _mock_get_kube_context_and_api_client,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_monitor.get_kube_context_and_api_client",
        _mock_get_kube_context_and_api_client,
    )


@pytest.fixture
def mock_maybe_create_image_pullsecret(monkeypatch):
    """Patches the kubernetes context and api client with a mock and returns it."""

    async def _mock_maybe_create_image_pullsecret(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_imagepull_secret",
        _mock_maybe_create_image_pullsecret,
    )


@pytest.fixture
def mock_create_from_dict(monkeypatch):
    """Patches the kubernetes create_from_dict with a mock and returns it."""
    function_mock = MagicMock()
    function_mock.return_value = [MockDict({"metadata": {"name": "test-job"}})]

    async def _mock_create_from_yaml(*args, **kwargs):
        return function_mock(*args, **kwargs)

    monkeypatch.setattr(
        "kubernetes_asyncio.utils.create_from_dict",
        lambda *args, **kwargs: _mock_create_from_yaml(*args, **kwargs),
    )
    return function_mock
