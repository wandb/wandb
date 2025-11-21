import asyncio
import base64
import json
import platform
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import kubernetes_asyncio
import pytest
import wandb
import wandb.sdk.launch.runner.kubernetes_runner
from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiException
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner.kubernetes_cleanup import KubernetesResourceCleanup
from wandb.sdk.launch.runner.kubernetes_monitor import (
    WANDB_K8S_LABEL_AUXILIARY_RESOURCE,
    CustomResource,
    LaunchKubernetesMonitor,
    _is_container_creating,
    _log_err_task_callback,
    _state_from_conditions,
    _state_from_replicated_status,
)
from wandb.sdk.launch.runner.kubernetes_runner import (
    KubernetesRunner,
    KubernetesSubmittedRun,
    add_entrypoint_args_overrides,
    add_label_to_pods,
    add_wandb_env,
    ensure_api_key_secret,
    maybe_create_imagepull_secret,
    maybe_create_wandb_team_secrets_secret,
)


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


def test_add_env(manifest):
    """Test that env vars are added to custom k8s specs."""
    env = {
        "TEST_ENV": "test_value",
        "TEST_ENV_2": "test_value_2",
        "WANDB_RUN_ID": "test_run_id",
    }
    add_wandb_env(manifest, env)
    assert manifest["spec"]["template"]["spec"]["containers"][0]["env"] == [
        {"name": "MY_ENV_VAR", "value": "MY_VALUE"},
        {"name": "TEST_ENV", "value": "test_value"},
        {"name": "TEST_ENV_2", "value": "test_value_2"},
        {"name": "WANDB_RUN_ID", "value": "test_run_id"},
    ]
    assert manifest["spec"]["template"]["spec"]["containers"][1]["env"] == [
        {"name": "TEST_ENV", "value": "test_value"},
        {"name": "TEST_ENV_2", "value": "test_value_2"},
    ]


def test_add_label(manifest):
    """Test that we add labels to pod specs correctly."""
    add_label_to_pods(manifest, "test_label", "test_value")
    assert manifest["spec"]["template"]["metadata"]["labels"] == {
        "app": "wandb",
        "test_label": "test_value",
    }


def test_add_entrypoint_args_overrides(manifest):
    """Test that we add entrypoint args to pod specs correctly."""
    overrides = {"args": ["--test_arg", "test_value"], "command": ["test_entry"]}
    add_entrypoint_args_overrides(manifest, overrides)
    assert manifest["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "--test_arg",
        "test_value",
    ]
    assert manifest["spec"]["template"]["spec"]["containers"][1]["args"] == [
        "--test_arg",
        "test_value",
    ]
    assert manifest["spec"]["template"]["spec"]["containers"][0]["command"] == [
        "test_entry"
    ]
    assert manifest["spec"]["template"]["spec"]["containers"][1]["command"] == [
        "test_entry"
    ]


@pytest.fixture
def volcano_spec():
    return {
        "apiVersion": "batch.volcano.sh/v1alpha1",
        "kind": "Job",
        "metadata": {"name": "test-job"},
        "tasks": [
            {
                "name": "master",
                "replicas": 1,
                "template": {
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
                    }
                },
            }
        ],
    }


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


class MockPodList:
    def __init__(self, pods):
        self.pods = pods

    @property
    def items(self):
        return self.pods


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

    async def list_namespaced_job(
        self, namespace, field_selector=None, label_selector=None
    ):
        mock_list = MagicMock()
        mock_list.items = [self.jobs[name] for name in self.jobs]
        return mock_list

    async def create_job(self, body):
        self.jobs[body["metadata"]["generateName"]] = body
        return body


class MockCoreV1Api:
    def __init__(self):
        self.pods = dict()
        self.secrets = []
        self.services = []
        self.calls = {"delete": 0}
        self.namespaces = []

    async def list_namespaced_pod(
        self, label_selector=None, namespace="default", field_selector=None
    ):
        ret = []
        for _, pod in self.pods.items():
            ret.append(pod)
        return MockPodList(ret)

    async def read_namespaced_pod(self, name, namespace):
        return self.pods[name]

    async def delete_namespaced_pod(self, name, namespace):
        if name in self.pods:
            del self.pods[name]
        self.calls["delete"] += 1

    async def list_namespaced_service(self, namespace, label_selector=None):
        mock_list = MagicMock()
        mock_list.items = self.services
        return mock_list

    async def delete_namespaced_service(self, name, namespace):
        self.services = [s for s in self.services if s.metadata.name != name]
        self.calls["delete"] += 1

    async def list_namespaced_secret(self, namespace, label_selector=None):
        mock_list = MagicMock()
        # Filter by namespace
        filtered = [s[1] for s in self.secrets if s[0] == namespace]
        mock_list.items = filtered
        return mock_list

    async def delete_namespaced_secret(self, namespace, name):
        self.secrets = list(
            filter(
                lambda s: not (s[0] == namespace and s[1].metadata.name == name),
                self.secrets,
            )
        )
        self.calls["delete"] += 1

    async def create_namespaced_secret(self, namespace, body):
        for s in self.secrets:
            if s[0] == namespace and s[1].metadata.name == body.metadata.name:
                raise ApiException(status=409)

        self.secrets.append((namespace, body))

    async def read_namespaced_secret(self, namespace, name):
        for s in self.secrets:
            if s[0] == namespace and s[1].metadata.name == name:
                return s[1]

    async def create_namespace(self, body):
        self.namespaces.append(body)

    async def delete_namespace(self, name):
        self.namespaces.remove(name)


class MockCustomObjectsApi:
    def __init__(self):
        self.jobs = dict()

    async def create_namespaced_custom_object(
        self, group, version, namespace, plural, body
    ):
        self.jobs[body["metadata"]["name"]] = body
        return body

    async def delete_namespaced_custom_object(
        self, group, version, namespace, plural, name, body
    ):
        del self.jobs[name]

    async def read_namespaced_custom_object(
        self, group, version, namespace, plural, name, body
    ):
        return self.jobs[name]

    async def get_namespaced_custom_object_status(
        self, group, version, namespace, plural, name, body
    ):
        return self.jobs[name]

    async def list_namespaced_custom_object(
        self, group, version, namespace, plural, field_selector=None
    ):
        return [self.jobs[name] for name in self.jobs]


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
def mock_core_api(monkeypatch):
    """Patches the kubernetes core api with a mock and returns it."""
    core_api = MockCoreV1Api()
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.client.CoreV1Api",
        lambda *args, **kwargs: core_api,
    )
    return core_api


@pytest.fixture
def mock_custom_api(monkeypatch):
    """Patches the kubernetes custom api with a mock and returns it."""
    custom_api = MockCustomObjectsApi()
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.client.CustomObjectsApi",
        lambda *args, **kwargs: custom_api,
    )
    return custom_api


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
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_cleanup.get_kube_context_and_api_client",
        _mock_get_kube_context_and_api_client,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.utils.get_kube_context_and_api_client",
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


@pytest.fixture
def mock_apps_api(monkeypatch):
    """Patches the kubernetes apps api with a mock and returns it."""
    apps_api = MagicMock()
    apps_api.list_namespaced_deployment = AsyncMock()
    apps_api.delete_namespaced_deployment = AsyncMock()
    monkeypatch.setattr(
        "kubernetes_asyncio.client.AppsV1Api",
        lambda *args, **kwargs: apps_api,
    )
    return apps_api


@pytest.fixture
def mock_network_api(monkeypatch):
    """Patches the kubernetes network api with a mock and returns it."""
    network_api = MagicMock()
    network_api.list_namespaced_network_policy = AsyncMock()
    network_api.delete_namespaced_network_policy = AsyncMock()
    monkeypatch.setattr(
        "kubernetes_asyncio.client.NetworkingV1Api",
        lambda *args, **kwargs: network_api,
    )
    return network_api


@pytest.mark.asyncio
@pytest.mark.xfail(reason="This test is flaky")
async def test_launch_kube_works(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    mock_create_from_dict,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    """Test that we can launch a kubernetes job."""
    mock_batch_api.jobs = {"test-job": MockDict(manifest)}
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    submitted_run = await runner.run(project, "hello-world")
    await asyncio.sleep(1)
    assert str(await submitted_run.get_status()) == "unknown"
    job_stream, pod_stream = mock_event_streams
    await pod_stream.add(  # This event does nothing. Added for code coverage of the path where there is no status.
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"labels": {"job-name": "test-job"}},
                    "status": {"phase": "Pending"},
                },
            }
        )
    )
    await pod_stream.add(
        MockDict(
            {
                "type": "ADDED",
                "object": {
                    "metadata": {"labels": {"job-name": "test-job"}},
                    "status": {"phase": "Pending"},
                },
            }
        )
    )
    await asyncio.sleep(0.1)
    assert str(await submitted_run.get_status()) == "unknown"
    await pod_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {
                        "name": "test-pod",
                        "labels": {"job-name": "test-job"},
                    },
                    "status": {
                        "phase": "Pending",
                        "container_statuses": [
                            {
                                "name": "master",
                                "state": {"waiting": {"reason": "ContainerCreating"}},
                            }
                        ],
                    },
                },
            }
        )
    )
    await asyncio.sleep(0.1)
    assert str(await submitted_run.get_status()) == "running"
    await job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"name": "test-job"},
                    "status": {"succeeded": 1},
                },
            }
        )
    )
    await asyncio.sleep(0.1)
    assert str(await submitted_run.get_status()) == "finished"
    assert mock_create_from_dict.call_count == 1
    submitted_manifest = mock_create_from_dict.call_args_list[0][0][1]
    assert submitted_manifest["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "--test_arg",
        "test_value",
    ]
    assert (
        submitted_manifest["spec"]["template"]["spec"]["containers"][0][
            "imagePullPolicy"
        ]
        == "IfNotPresent"
    )
    # Test cancel
    assert "test-job" in mock_batch_api.jobs
    await submitted_run.cancel()
    assert "test-job" not in mock_batch_api.jobs

    def _raise_api_exception(*args, **kwargs):
        raise ApiException()

    mock_batch_api.delete_namespaced_job = _raise_api_exception
    with pytest.raises(LaunchError):
        await submitted_run.cancel()


@pytest.mark.asyncio
async def test_launch_crd_works(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_custom_api,
    mock_kube_context_and_api_client,
    mock_create_from_dict,
    test_api,
    volcano_spec,
    clean_monitor,
    clean_agent,
):
    """Test that we can launch a kubernetes job."""
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_imagepull_secret",
        lambda *args, **kwargs: None,
    )
    mock_batch_api.jobs = {"test-job": MockDict(volcano_spec)}
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": volcano_spec},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    submitted_run = await runner.run(project, MagicMock())
    assert str(await submitted_run.get_status()) == "unknown"
    job_stream, pod_stream = mock_event_streams
    # add container creating event
    await pod_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {
                        "name": "test-pod",
                        "labels": {"job-name": "test-job"},
                    },
                    "status": {
                        "phase": "Pending",
                        "container_statuses": [
                            {
                                "name": "master",
                                "state": {"waiting": {"reason": "ContainerCreating"}},
                            }
                        ],
                    },
                },
            }
        )
    )
    await asyncio.sleep(1)
    assert str(await submitted_run.get_status()) == "running"
    await job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"name": "test-job"},
                    "status": {"state": {"phase": "Running"}},
                },
            }
        )
    )
    await asyncio.sleep(1)
    assert str(await submitted_run.get_status()) == "running"
    await job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"name": "test-job"},
                    "status": {
                        "conditions": [
                            {
                                "type": "Succeeded",
                                "status": "True",
                                "lastTransitionTime": "2021-09-06T20:04:12Z",
                            }
                        ]
                    },
                },
            }
        )
    )
    await asyncio.sleep(1)
    assert str(await submitted_run.get_status()) == "finished"


@pytest.mark.asyncio
async def test_launch_crd_pod_schedule_warning(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_custom_api,
    mock_kube_context_and_api_client,
    mock_create_from_dict,
    test_api,
    volcano_spec,
    clean_monitor,
    clean_agent,
):
    mock_batch_api.jobs = {"test-job": MockDict(volcano_spec)}
    test_api.update_run_queue_item_warning = MagicMock(return_value=True)
    job_tracker = MagicMock()
    job_tracker.run_queue_item_id = "test-rqi"
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": volcano_spec},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    submitted_run = await runner.run(project, "hello-world")
    await asyncio.sleep(1)
    _, pod_stream = mock_event_streams
    await pod_stream.add(
        MockDict(
            {
                "type": "WARNING",
                "object": {
                    "metadata": {
                        "owner_references": [{"name": "test-job"}],
                        "labels": {},
                    },
                    "status": {
                        "phase": "Pending",
                        "conditions": [
                            {
                                "type": "PodScheduled",
                                "status": "False",
                                "reason": "Unschedulable",
                                "message": "Test message",
                            }
                        ],
                    },
                },
            }
        )
    )
    await asyncio.sleep(0.1)
    status = await submitted_run.get_status()
    assert status.messages == ["Test message"]


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Launch does not support Windows and this test is failing on Windows.",
)
@pytest.mark.asyncio
async def test_launch_kube_base_image_works(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    mock_create_from_dict,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
    tmpdir,
):
    """Test that runner works as expected with base image jobs."""
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner,
        "SOURCE_CODE_PVC_MOUNT_PATH",
        tmpdir,
    )
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner,
        "SOURCE_CODE_PVC_NAME",
        "wandb-source-code-pvc",
    )
    mock_batch_api.jobs = {"test-job": MockDict(manifest)}
    project = LaunchProject(
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
        docker_config={},
    )
    project._job_artifact = MagicMock()
    project.set_job_base_image("test_base_image")
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )

    await runner.run(project, "test_base_image")
    manifest = mock_create_from_dict.call_args_list[0][0][1]
    pod = manifest["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["workingDir"] == "/mnt/wandb"
    assert container["volumeMounts"] == [
        {
            "mountPath": "/mnt/wandb",
            "subPath": project.get_image_source_string(),
            "name": "wandb-source-code-volume",
        }
    ]
    assert pod["volumes"] == [
        {
            "name": "wandb-source-code-volume",
            "persistentVolumeClaim": {"claimName": "wandb-source-code-pvc"},
        }
    ]


@pytest.mark.skip(
    reason="This test is flaky, please remove the skip once the flakyness is fixed."
)
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Launch does not support Windows and this test is failing on Windows.",
)
@pytest.mark.asyncio
async def test_launch_crd_base_image_works(
    monkeypatch,
    mock_event_streams,
    mock_custom_api,
    mock_kube_context_and_api_client,
    test_api,
    volcano_spec,
    tmpdir,
):
    """Test that runner works as expected with base image jobs."""
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner,
        "SOURCE_CODE_PVC_MOUNT_PATH",
        tmpdir,
    )
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner,
        "SOURCE_CODE_PVC_NAME",
        "wandb-source-code-pvc",
    )
    mock_batch_api.jobs = {"test-job": MockDict(volcano_spec)}
    project = LaunchProject(
        docker_config={},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": volcano_spec},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    project._job_artifact = MagicMock()
    project.set_job_base_image("test_base_image")
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    await runner.run(project, "test_base_image")
    job = mock_custom_api.jobs["test-job"]
    pod = job["tasks"][0]["template"]["spec"]
    container = pod["containers"][0]
    assert container["workingDir"] == "/mnt/wandb"
    assert container["volumeMounts"] == [
        {
            "mountPath": "/mnt/wandb",
            "subPath": project.get_image_source_string(),
            "name": "wandb-source-code-volume",
        }
    ]
    assert pod["volumes"] == [
        {
            "name": "wandb-source-code-volume",
            "persistentVolumeClaim": {"claimName": "wandb-source-code-pvc"},
        }
    ]


@pytest.mark.timeout(320)
@pytest.mark.asyncio
async def test_launch_kube_failed(
    monkeypatch,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_create_from_dict,
    mock_maybe_create_image_pullsecret,
    mock_event_streams,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    """Test that we can launch a kubernetes job."""
    mock_batch_api.jobs = {"test-job": manifest}
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    job_stream, _ = mock_event_streams
    await job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": {
                    "metadata": {"name": "test-job"},
                    "status": {"failed": 1},
                },
            }
        )
    )
    submitted_run = await runner.run(project, "test_image")
    await submitted_run.wait()
    assert str(await submitted_run.get_status()) == "failed"


@pytest.mark.timeout(320)
@pytest.mark.asyncio
async def test_launch_kube_api_secret_failed(
    monkeypatch,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_create_from_dict,
    mock_maybe_create_image_pullsecret,
    mock_event_streams,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    async def mock_maybe_create_imagepull_secret(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_imagepull_secret",
        mock_maybe_create_imagepull_secret,
    )
    mock_la = MagicMock()
    mock_la.initialized = MagicMock(return_value=True)

    monkeypatch.setattr("wandb.sdk.launch.agent.agent.LaunchAgent", mock_la)

    async def mock_create_namespaced_secret(*args, **kwargs):
        raise Exception("Test exception")

    mock_core_api = MagicMock()
    mock_core_api.create_namespaced_secret = mock_create_namespaced_secret
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.kubernetes_asyncio.client.CoreV1Api",
        mock_core_api,
    )
    monkeypatch.setattr("wandb.termwarn", MagicMock())
    mock_batch_api.jobs = {"test-job": MockDict(manifest)}
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={"_wandb_api_key": "test_key"},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    with pytest.raises(LaunchError):
        await runner.run(project, MagicMock())

    assert wandb.termwarn.call_count == 6
    assert wandb.termwarn.call_args_list[0][0][0].startswith(
        "Exception when ensuring Kubernetes API key secret"
    )


@pytest.mark.asyncio
async def test_launch_kube_pod_schedule_warning(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    mock_create_from_dict,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    mock_batch_api.jobs = {"test-job": MockDict(manifest)}
    job_tracker = MagicMock()
    job_tracker.run_queue_item_id = "test-rqi"
    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={},
        overrides={
            "args": ["--test_arg", "test_value"],
            "command": ["test_entry"],
        },
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )
    submitted_run = await runner.run(project, "hello-world")
    await asyncio.sleep(1)
    _, pod_stream = mock_event_streams
    await pod_stream.add(
        MockDict(
            {
                "type": "WARNING",
                "object": {
                    "metadata": {"labels": {"job-name": "test-job"}},
                    "status": {
                        "phase": "Pending",
                        "conditions": [
                            {
                                "type": "PodScheduled",
                                "status": "False",
                                "reason": "Unschedulable",
                                "message": "Test message",
                            }
                        ],
                    },
                },
            }
        )
    )
    await asyncio.sleep(0.1)
    status = await submitted_run.get_status()
    assert status.messages == ["Test message"]


@pytest.mark.asyncio
async def test_maybe_create_imagepull_secret_given_creds():
    mock_registry = MagicMock()

    async def _mock_get_username_password():
        return ("testuser", "testpass")

    mock_registry.get_username_password.return_value = _mock_get_username_password()
    mock_registry.uri = "test.com"
    api = MockCoreV1Api()
    await maybe_create_imagepull_secret(
        api,
        mock_registry,
        "12345678",
        "wandb",
    )
    namespace, secret = api.secrets[0]
    assert namespace == "wandb"
    assert secret.metadata.name == "regcred-12345678"
    assert secret.data[".dockerconfigjson"] == base64.b64encode(
        json.dumps(
            {
                "auths": {
                    "test.com": {
                        "auth": "dGVzdHVzZXI6dGVzdHBhc3M=",  # testuser:testpass
                        "email": "deprecated@wandblaunch.com",
                    }
                }
            }
        ).encode("utf-8")
    ).decode("utf-8")


@pytest.mark.asyncio
async def test_create_api_key_secret():
    api = MockCoreV1Api()
    await ensure_api_key_secret(api, "wandb-api-key-testagent", "wandb", "testsecret")
    namespace, secret = api.secrets[0]
    assert namespace == "wandb"
    assert secret.metadata.name == "wandb-api-key-testagent"
    assert secret.data["password"] == base64.b64encode(b"testsecret").decode()


@pytest.mark.asyncio
async def test_create_api_key_secret_exists():
    api = MockCoreV1Api()

    # Create secret with same name but different data, assert it gets overwritten
    secret_data = "bad data"
    labels = {"wandb.ai/created-by": "launch-agent"}
    secret = client.V1Secret(
        data=secret_data,
        metadata=client.V1ObjectMeta(
            name="wandb-api-key-testagent", namespace="wandb", labels=labels
        ),
        kind="Secret",
        type="kubernetes.io/basic-auth",
    )
    await api.create_namespaced_secret("wandb", secret)

    await ensure_api_key_secret(api, "wandb-api-key-testagent", "wandb", "testsecret")
    namespace, secret = api.secrets[0]
    assert namespace == "wandb"
    assert secret.metadata.name == "wandb-api-key-testagent"
    assert secret.data["password"] == base64.b64encode(b"testsecret").decode()
    assert api.calls["delete"] == 1


@pytest.mark.asyncio
async def test_create_env_vars_secret():
    api = MockCoreV1Api()
    env_vars = {
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "API_SECRET": "secret123",
        "DEBUG_MODE": "true",
    }
    await maybe_create_wandb_team_secrets_secret(
        api, "wandb-secrets-testrun", "wandb", env_vars
    )

    namespace, secret = api.secrets[0]
    assert namespace == "wandb"
    assert secret.metadata.name == "wandb-secrets-testrun"
    assert secret.type == "Opaque"

    # Verify all env vars are base64 encoded in the secret
    expected_data = {
        "DATABASE_URL": base64.b64encode(
            b"postgresql://user:pass@localhost/db"
        ).decode(),
        "API_SECRET": base64.b64encode(b"secret123").decode(),
        "DEBUG_MODE": base64.b64encode(b"true").decode(),
    }
    assert secret.data == expected_data


@pytest.mark.asyncio
async def test_create_env_vars_secret_exists():
    api = MockCoreV1Api()

    # Create secret with same name but different data, assert it gets overwritten
    secret_data = {"OLD_VAR": "old_value"}
    labels = {"wandb.ai/created-by": "launch-agent"}
    secret = client.V1Secret(
        data=secret_data,
        metadata=client.V1ObjectMeta(
            name="wandb-secrets-testrun", namespace="wandb", labels=labels
        ),
        kind="Secret",
        type="Opaque",
    )
    await api.create_namespaced_secret("wandb", secret)

    env_vars = {
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "API_SECRET": "secret123",
    }
    await maybe_create_wandb_team_secrets_secret(
        api, "wandb-secrets-testrun", "wandb", env_vars
    )

    namespace, secret = api.secrets[0]
    assert namespace == "wandb"
    assert secret.metadata.name == "wandb-secrets-testrun"
    expected_data = {
        "DATABASE_URL": base64.b64encode(
            b"postgresql://user:pass@localhost/db"
        ).decode(),
        "API_SECRET": base64.b64encode(b"secret123").decode(),
    }
    assert secret.data == expected_data
    assert api.calls["delete"] == 1


@pytest.mark.asyncio
async def test_create_env_vars_secret_exists_different_owner():
    api = MockCoreV1Api()

    # Create secret with same name but owned by someone else
    secret_data = {"OLD_VAR": "old_value"}
    labels = {"owner": "someone-else"}  # Not launch-agent
    secret = client.V1Secret(
        data=secret_data,
        metadata=client.V1ObjectMeta(
            name="wandb-secrets-testrun", namespace="wandb", labels=labels
        ),
        kind="Secret",
        type="Opaque",
    )
    await api.create_namespaced_secret("wandb", secret)

    env_vars = {"DATABASE_URL": "postgresql://user:pass@localhost/db"}

    # Should raise LaunchError since we can't overwrite someone else's secret
    with pytest.raises(
        LaunchError,
        match="Kubernetes secret already exists in namespace wandb with incorrect data",
    ):
        await maybe_create_wandb_team_secrets_secret(
            api, "wandb-secrets-testrun", "wandb", env_vars
        )


# Test monitor class.


def job_factory(name, statuses, type="MODIFIED"):
    """Factory for creating job events."""
    return MockDict(
        {
            "type": f"{type}",
            "object": {
                "status": {f"{status}": 1 for status in statuses},
                "metadata": {"name": name},
            },
        }
    )


def pod_factory(event_type, job_name, condition_types, condition_reasons, phase=None):
    """Factory for creating pod events.

    Args:
        event_type (str): The type of event to create.
        condition_types (list): The types of conditions to create.
        condition_reasons (list): The reasons of conditions to create.

    Returns:
        dict: The pod event.
    """
    return MockDict(
        {
            "type": event_type,
            "object": {
                "metadata": {
                    "labels": {"job-name": job_name},
                },
                "status": {
                    "phase": phase,
                    "conditions": [
                        {
                            "type": condition_type,
                            "reason": condition_reason,
                        }
                        for condition_type, condition_reason in zip(
                            condition_types, condition_reasons
                        )
                    ],
                },
            },
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    ["EvictionByEvictionAPI", "PreemptionByScheduler", "TerminationByKubelet"],
)
async def test_monitor_preempted(
    mock_event_streams,
    mock_kube_context_and_api_client,
    mock_batch_api,
    mock_core_api,
    reason,
    clean_monitor,
    clean_agent,
):
    """Test if the monitor thread detects a preempted job."""
    await LaunchKubernetesMonitor.ensure_initialized()
    LaunchKubernetesMonitor.monitor_namespace("wandb")
    _, pod_event_stream = mock_event_streams
    await pod_event_stream.add(pod_factory("ADDED", "test-job", [], []))
    await asyncio.sleep(0.1)
    await pod_event_stream.add(
        pod_factory("MODIFIED", "test-job", ["DisruptionTarget"], [reason])
    )
    await asyncio.sleep(0.1)
    assert LaunchKubernetesMonitor.get_status("test-job").state == "preempted"


@pytest.mark.asyncio
async def test_monitor_succeeded(
    mock_event_streams,
    mock_kube_context_and_api_client,
    mock_batch_api,
    mock_core_api,
    clean_monitor,
    clean_agent,
):
    """Test if the monitor thread detects a succeeded job."""
    await LaunchKubernetesMonitor.ensure_initialized()
    LaunchKubernetesMonitor.monitor_namespace("wandb")
    job_event_stream, pod_event_stream = mock_event_streams
    await asyncio.sleep(0.1)
    await pod_event_stream.add(pod_factory("ADDED", "job-name", [], []))
    await asyncio.sleep(0.1)
    await job_event_stream.add(job_factory("job-name", ["succeeded"]))
    await asyncio.sleep(0.1)
    assert LaunchKubernetesMonitor.get_status("job-name").state == "finished"


@pytest.mark.asyncio
async def test_monitor_failed(
    mock_event_streams,
    mock_kube_context_and_api_client,
    mock_batch_api,
    mock_core_api,
    clean_monitor,
    clean_agent,
):
    """Test if the monitor thread detects a failed job."""
    await LaunchKubernetesMonitor.ensure_initialized()
    LaunchKubernetesMonitor.monitor_namespace("wandb")
    job_event_stream, pod_event_stream = mock_event_streams
    await asyncio.sleep(0.1)
    await pod_event_stream.add(pod_factory("ADDED", "job-name", [], []))
    await asyncio.sleep(0.1)
    await job_event_stream.add(job_factory("job-name", ["failed"]))
    await asyncio.sleep(0.1)
    assert LaunchKubernetesMonitor.get_status("job-name").state == "failed"


@pytest.mark.asyncio
async def test_monitor_running(
    mock_event_streams,
    mock_kube_context_and_api_client,
    mock_batch_api,
    mock_core_api,
    clean_monitor,
    clean_agent,
):
    """Test if the monitor thread detects a running job."""
    await LaunchKubernetesMonitor.ensure_initialized()
    LaunchKubernetesMonitor.monitor_namespace("wandb")
    job_event_stream, pod_event_stream = mock_event_streams
    await asyncio.sleep(0.1)
    await pod_event_stream.add(pod_factory("ADDED", "job-name", [], []))
    await asyncio.sleep(0.1)
    await job_event_stream.add(job_factory("job-name", ["active"]))
    await pod_event_stream.add(
        pod_factory("MODIFIED", "job-name", [""], [""], phase="Running")
    )
    await asyncio.sleep(0.1)
    assert LaunchKubernetesMonitor.get_status("job-name").state == "running"


@pytest.mark.asyncio
async def test_monitor_job_deleted(
    mock_event_streams,
    mock_kube_context_and_api_client,
    mock_batch_api,
    mock_core_api,
    clean_monitor,
    clean_agent,
):
    """Test if the monitor thread detects a job being deleted."""
    await LaunchKubernetesMonitor.ensure_initialized()
    LaunchKubernetesMonitor.monitor_namespace("wandb")
    job_event_stream, pod_event_stream = mock_event_streams
    await asyncio.sleep(0.1)
    await pod_event_stream.add(pod_factory("ADDED", "job-name", [], []))
    await asyncio.sleep(0.1)
    await job_event_stream.add(job_factory("job-name", ["active"], type="DELETED"))
    await asyncio.sleep(0.1)
    assert LaunchKubernetesMonitor.get_status("job-name").state == "failed"


# Test util functions


def condition_factory(
    condition_type, condition_status, condition_reason, transition_time
):
    """Factory for creating conditions."""
    return MockDict(
        {
            "type": condition_type,
            "status": condition_status,
            "reason": condition_reason,
            "lastTransitionTime": transition_time,
        }
    )


@pytest.mark.parametrize(
    "conditions, expected",
    [
        (
            [condition_factory("Running", "True", "", "2023-09-06T20:04:11Z")],
            "running",
        ),
        (
            [
                condition_factory("Running", "False", "", "2023-09-06T20:04:11Z"),
                condition_factory("Succeeded", "True", "", "2023-09-06T20:04:11Z"),
            ],
            "finished",
        ),
        (
            [
                condition_factory("Running", "True", "", "2023-09-06T20:04:11Z"),
                condition_factory("Terminating", "True", "", "2023-09-06T20:04:11Z"),
            ],
            "stopping",
        ),
        ([condition_factory("Running", False, "", "2023-09-06T20:04:11Z")], None),
    ],
)
def test_state_from_conditions(conditions, expected):
    """Test that we extract CRD state from conditions correctly."""
    state = _state_from_conditions(conditions)
    if isinstance(state, str):
        assert state == expected
    else:
        assert state == expected and state is None


def container_status_factory(reason):
    """Factory for creating container statuses."""
    return MockDict({"state": {"waiting": {"reason": reason}}})


@pytest.mark.parametrize(
    "conditions, expected",
    [
        (
            [container_status_factory("ContainerCreating")],
            True,
        ),
        (
            [container_status_factory("PodInitializing")],
            False,
        ),
    ],
)
def test_is_container_creating(conditions, expected):
    pod = MockDict({"container_statuses": conditions})
    assert _is_container_creating(pod) == expected


@pytest.mark.parametrize(
    "status_dict,expected",
    [
        ({}, None),
        ({"ready": 1}, "running"),
        ({"active": 1}, "starting"),
    ],
)
def test_state_from_replicated_status(status_dict, expected):
    """Test that we extract replicated job state from status correctly."""
    state = _state_from_replicated_status(status_dict)
    assert state == expected


def test_custom_resource_helper():
    """Test that the custom resource helper class works as expected."""
    resource = CustomResource("batch.volcano.sh", "v1alpha1", "jobs")
    assert resource.group == "batch.volcano.sh"
    assert resource.version == "v1alpha1"
    assert resource.plural == "jobs"
    assert str(resource) == "batch.volcano.sh/v1alpha1/jobs"
    assert hash(resource) == hash(str(resource))


@pytest.mark.asyncio
async def test_log_error_callback(monkeypatch):
    """Test that our callback logs exceptions for crashed tasks."""
    monkeypatch.setattr("wandb.termerror", MagicMock())

    async def _error_raiser():
        raise LaunchError("test error")

    task = asyncio.create_task(_error_raiser())
    task.add_done_callback(_log_err_task_callback)
    with pytest.raises(LaunchError):
        await task
    assert wandb.termerror.call_count == 2
    assert wandb.termerror.call_args_list[0][0][0].startswith("Exception in task")


# Tests for KubernetesSubmittedRun


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pods,logs,expected",
    [
        (
            MockPodList(
                [
                    MockDict(
                        {
                            "metadata": MockDict(
                                {
                                    "name": "test_pod",
                                    "labels": {"job-name": "test_job"},
                                }
                            )
                        }
                    )
                ]
            ),
            "test_log",
            "test_log",
        ),
        (MockPodList([]), "test_log", None),
        (Exception(), "test_log", None),
        (
            MockPodList(
                [
                    MockDict(
                        {
                            "metadata": MockDict(
                                {
                                    "name": "test_pod",
                                    "labels": {"job-name": "test_job"},
                                }
                            )
                        }
                    )
                ]
            ),
            Exception(),
            None,
        ),
    ],
)
async def test_kubernetes_submitted_run_get_logs(pods, logs, expected):
    core_api = MagicMock()

    async def _mock_list_namespaced_pod(*args, **kwargs):
        if isinstance(pods, Exception):
            raise pods
        return pods

    async def _mock_read_namespaced_pod_log(*args, **kwargs):
        if isinstance(logs, Exception):
            raise logs
        return logs

    core_api.list_namespaced_pod = _mock_list_namespaced_pod
    core_api.read_namespaced_pod_log = _mock_read_namespaced_pod_log

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    # Assert that we get the logs back.
    assert await submitted_run.get_logs() == expected


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_get_job_api_key_with_secret():
    """Test that get_job_api_key retrieves API key from Kubernetes secret."""
    import base64

    core_api = MagicMock()

    api_key = "test_api_key_123"
    api_key_b64 = base64.b64encode(api_key.encode()).decode()

    mock_secret = MagicMock()
    mock_secret.data = {"password": api_key_b64}

    core_api.read_namespaced_secret = AsyncMock(return_value=mock_secret)

    secret_mock = MagicMock()
    secret_mock.metadata.name = "test-api-key-secret"
    secret_mock.metadata.namespace = "wandb"

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    submitted_run.secret = secret_mock

    result = await submitted_run.get_job_api_key()
    assert result == api_key

    core_api.read_namespaced_secret.assert_called_once_with(
        name="test-api-key-secret", namespace="wandb"
    )


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_get_job_api_key_no_secret():
    """Test that get_job_api_key returns None when no secret is set."""
    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=MagicMock(),
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    # No secret set
    assert submitted_run.secret is None

    result = await submitted_run.get_job_api_key()
    assert result is None


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_get_job_api_key_secret_read_fails():
    """Test that get_job_api_key returns None when secret read fails."""
    core_api = MagicMock()
    core_api.read_namespaced_secret = AsyncMock(
        side_effect=Exception("Secret not found")
    )

    secret_mock = MagicMock()
    secret_mock.metadata.name = "test-api-key-secret"
    secret_mock.metadata.namespace = "wandb"

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    submitted_run.secret = secret_mock

    result = await submitted_run.get_job_api_key()
    assert result is None


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_cleanup_job_api_key_secret_success():
    """Test that cleanup_job_api_key_secret deletes the secret successfully."""
    core_api = MagicMock()
    core_api.delete_namespaced_secret = AsyncMock()

    secret_mock = MagicMock()
    secret_mock.metadata.name = "test-api-key-secret"
    secret_mock.metadata.namespace = "wandb"

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    submitted_run.secret = secret_mock

    await submitted_run.cleanup_job_api_key_secret()

    core_api.delete_namespaced_secret.assert_called_once_with(
        name="test-api-key-secret", namespace="wandb"
    )


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_cleanup_job_api_key_secret_no_secret():
    """Test that cleanup_job_api_key_secret does nothing when no secret is set."""
    core_api = MagicMock()
    core_api.delete_namespaced_secret = AsyncMock()

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )

    assert submitted_run.secret is None

    await submitted_run.cleanup_job_api_key_secret()

    core_api.delete_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_cleanup_noop_when_no_additional_services(
    monkeypatch,
    mock_create_from_dict,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    clean_agent,
    clean_monitor,
):
    """End-to-end test that verifies no cleanup when there are no additional services.

    This test verifies that when a KubernetesRunner.run() is called with a launch_spec
    that has no additional_services, the returned KubernetesSubmittedRun has
    auxiliary_resource_label_key=None and cleanup methods don't call delete APIs.
    """
    # Mock additional helper functions not covered by fixtures
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.ensure_api_key_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_wandb_team_secrets_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.ensure_initialized",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.monitor_namespace",
        MagicMock(),
    )

    # Spy on cleanup methods
    mock_batch_api.list_namespaced_job = AsyncMock()
    mock_batch_api.delete_namespaced_job = AsyncMock()
    mock_core_api.list_namespaced_service = AsyncMock()
    mock_core_api.delete_namespaced_service = AsyncMock()
    mock_core_api.list_namespaced_pod = AsyncMock()
    mock_core_api.delete_namespaced_pod = AsyncMock()
    mock_core_api.list_namespaced_secret = AsyncMock()
    mock_core_api.delete_namespaced_secret = AsyncMock()

    # Create a mock launch project WITHOUT additional_services
    launch_project = MagicMock()
    launch_project.target_entity = "test-entity"
    launch_project.target_project = "test-project"
    launch_project.run_id = "test-run-id"
    launch_project.name = "test-name"
    launch_project.author = "test-author"
    launch_project.resource_args = {"kubernetes": {"kind": "Job"}}
    launch_project.launch_spec = {"_resume_count": 0}  # No additional_services
    launch_project.override_args = []
    launch_project.override_entrypoint = None
    launch_project.get_single_entry_point.return_value = None
    launch_project.fill_macros = lambda image_uri: {"kubernetes": {"kind": "Job"}}
    launch_project.docker_config = {}
    launch_project.job_base_image = None

    # Create the runner
    api = MagicMock()
    environment = MagicMock()
    registry = MagicMock()
    backend_config = {"SYNCHRONOUS": False}

    runner = KubernetesRunner(api, backend_config, environment, registry)

    # Run and get the submitted run
    submitted_run = await runner.run(launch_project, "test-image:latest")

    # Verify the submitted run has no auxiliary_resource_label_key
    assert submitted_run is not None
    assert submitted_run.auxiliary_resource_label_key is None

    # Call cleanup
    await submitted_run._delete_auxiliary_resources_by_label()

    # Verify that no delete methods were called
    mock_batch_api.list_namespaced_job.assert_not_called()
    mock_batch_api.delete_namespaced_job.assert_not_called()
    mock_core_api.list_namespaced_service.assert_not_called()
    mock_core_api.delete_namespaced_service.assert_not_called()
    mock_core_api.list_namespaced_pod.assert_not_called()
    mock_core_api.delete_namespaced_pod.assert_not_called()
    mock_core_api.list_namespaced_secret.assert_not_called()
    mock_core_api.delete_namespaced_secret.assert_not_called()
    mock_apps_api.list_namespaced_deployment.assert_not_called()
    mock_apps_api.delete_namespaced_deployment.assert_not_called()
    mock_network_api.list_namespaced_network_policy.assert_not_called()
    mock_network_api.delete_namespaced_network_policy.assert_not_called()


def make_mock_resource_list(resource_names):
    """Helper to create mock resource lists."""

    mock_list = MagicMock()
    mock_items = []
    for name in resource_names:
        mock_item = MagicMock()
        mock_item.metadata.name = name
        mock_items.append(mock_item)
    mock_list.items = mock_items
    return mock_list


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_cleanup_with_additional_services(
    monkeypatch,
    mock_create_from_dict,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    clean_agent,
    clean_monitor,
):
    """End-to-end test that verifies cleanup when there are additional services.

    This test verifies that when a KubernetesRunner.run() is called with a launch_spec
    that has additional_services, the returned KubernetesSubmittedRun has
    auxiliary_resource_label_key and cleanup methods call delete APIs.
    """

    # Override mock API methods to return resources with items
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=make_mock_resource_list(["aux-service-1"])
    )
    mock_core_api.delete_namespaced_service = AsyncMock()

    # Mock additional helper functions not covered by fixtures
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.ensure_api_key_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_wandb_team_secrets_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.ensure_initialized",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.monitor_namespace",
        MagicMock(),
    )

    # Create a launch project WITH additional_services
    launch_project = MagicMock()
    launch_project.target_entity = "test-entity"
    launch_project.target_project = "test-project"
    launch_project.run_id = "test-run-id"
    launch_project.name = "test-name"
    launch_project.author = "test-author"
    launch_project.resource_args = {"kubernetes": {"kind": "Job"}}
    launch_project.launch_spec = {
        "_resume_count": 0,
        "additional_services": [{"config": {"kind": "Service"}}],
    }
    launch_project.override_args = []
    launch_project.override_entrypoint = None
    launch_project.get_single_entry_point.return_value = None
    launch_project.fill_macros = lambda image_uri: {"kubernetes": {"kind": "Job"}}
    launch_project.docker_config = {}
    launch_project.job_base_image = None

    # Create the runner
    api = MagicMock()
    environment = MagicMock()
    registry = MagicMock()
    backend_config = {"SYNCHRONOUS": False}

    runner = KubernetesRunner(api, backend_config, environment, registry)

    # Run and get the submitted run
    submitted_run = await runner.run(launch_project, "test-image:latest")

    # Verify the submitted run has an auxiliary_resource_label_key
    assert submitted_run is not None
    assert submitted_run.auxiliary_resource_label_key is not None

    # Call cleanup
    await submitted_run._delete_auxiliary_resources_by_label()

    # Verify that all list methods were called and delete methods were called for each resource
    mock_core_api.list_namespaced_service.assert_called_once()
    mock_core_api.delete_namespaced_service.assert_called_once_with(
        name="aux-service-1", namespace="default"
    )


@pytest.mark.asyncio
async def test_runner_cleanup_additional_services_on_creation_timeout(
    monkeypatch,
    mock_create_from_dict,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    clean_agent,
    clean_monitor,
):
    """Test that runner cleans up auxiliary resources when additional services creation times out."""

    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=make_mock_resource_list(["deploy-test-run"])
    )
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=make_mock_resource_list(["evals-test-run"])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=make_mock_resource_list(
            ["job-policy-test", "resource-policy-test"]
        )
    )

    # Mock delete methods
    mock_apps_api.delete_namespaced_deployment = AsyncMock()
    mock_core_api.delete_namespaced_service = AsyncMock()
    mock_network_api.delete_namespaced_network_policy = AsyncMock()

    # Mock helper functions
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.ensure_api_key_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_wandb_team_secrets_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.ensure_initialized",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.monitor_namespace",
        MagicMock(),
    )

    # Mock _wait_for_resource_ready to raise LaunchError (simulate timeout)
    async def mock_wait_for_resource_ready(
        self, api_client, config, namespace, timeout_seconds=300
    ):
        # Simulate deployment timeout
        if config.get("kind") == "Deployment":
            raise LaunchError(
                f"Resource '{config.get('metadata', {}).get('name')}' not ready within {timeout_seconds} seconds"
            )

    # Patch the wait method
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.KubernetesRunner._wait_for_resource_ready",
        mock_wait_for_resource_ready,
    )

    # Create launch project WITH additional_services that will timeout
    launch_project = MagicMock()
    launch_project.target_entity = "test-entity"
    launch_project.target_project = "test-project"
    launch_project.run_id = "test-run-id"
    launch_project.name = "test-name"
    launch_project.author = "test-author"
    launch_project.resource_args = {"kubernetes": {"kind": "Job"}}
    launch_project.launch_spec = {
        "_resume_count": 0,
        "additional_services": [
            {
                "name": "deployment",
                "config": {
                    "kind": "Deployment",
                    "metadata": {"name": "deploy-test-run"},
                    "spec": {"replicas": 1},
                },
            }
        ],
    }
    launch_project.override_args = []
    launch_project.override_entrypoint = None
    launch_project.get_single_entry_point.return_value = None
    launch_project.fill_macros = lambda image_uri: {"kubernetes": {"kind": "Job"}}
    launch_project.docker_config = {}
    launch_project.job_base_image = None
    launch_project.get_env_vars_dict = lambda _, __: {}
    launch_project.get_secrets_dict = lambda: {}

    # Create the runner
    api = MagicMock()
    environment = MagicMock()
    registry = MagicMock()
    backend_config = {"SYNCHRONOUS": False}

    runner = KubernetesRunner(api, backend_config, environment, registry)

    # Run should raise LaunchError due to timeout
    with pytest.raises(LaunchError, match="not ready within 300 seconds"):
        await runner.run(launch_project, "test-image:latest")

    # Verify cleanup was called for all resource types
    # Since deployment timed out, cleanup should delete it
    mock_apps_api.list_namespaced_deployment.assert_called()
    mock_apps_api.delete_namespaced_deployment.assert_called_once_with(
        name="deploy-test-run", namespace="default"
    )

    # Verify cleanup was also called for other resource types
    mock_core_api.list_namespaced_service.assert_called()
    mock_network_api.list_namespaced_network_policy.assert_called()


@pytest.mark.asyncio
async def test_kubernetes_submitted_run_cleanup_job_api_key_secret_delete_fails(
    monkeypatch,
):
    """Test that cleanup_job_api_key_secret handles deletion failures gracefully."""
    mock_termwarn = MagicMock()
    monkeypatch.setattr("wandb.termwarn", mock_termwarn)

    core_api = MagicMock()
    core_api.delete_namespaced_secret = AsyncMock(
        side_effect=Exception("Delete failed")
    )

    secret_mock = MagicMock()
    secret_mock.metadata.name = "test-api-key-secret"
    secret_mock.metadata.namespace = "wandb"

    submitted_run = KubernetesSubmittedRun(
        batch_api=MagicMock(),
        core_api=core_api,
        apps_api=MagicMock(),
        network_api=MagicMock(),
        namespace="wandb",
        name="test_run",
    )
    submitted_run.secret = secret_mock

    await submitted_run.cleanup_job_api_key_secret()

    core_api.delete_namespaced_secret.assert_called_once_with(
        name="test-api-key-secret", namespace="wandb"
    )

    assert mock_termwarn.call_count == 1
    assert "Failed to cleanup API key secret" in str(mock_termwarn.call_args)


@pytest.mark.asyncio
@patch(
    "wandb.sdk.launch.runner.kubernetes_runner.uuid.uuid4",
    return_value=uuid.UUID("123e4567-e89b-12d3-a456-426614174000"),
)
async def test_launch_additional_services(
    mock_uuid4,
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    mock_create_from_dict,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    target_entity = "test_entity"
    target_project = "test_project"
    run_id = "test_run_id"
    expected_deployment_name = "deploy-test-entity-test-project-test-run-id"
    expected_pod_name = "pod-test-entity-test-project-test-run-id"
    expected_label = "auxiliary-resource"

    # Add a very long label to the manifest that needs sanitization (>63 chars)
    manifest.setdefault("metadata", {}).setdefault("labels", {})["very_long_label"] = (
        "THIS_IS_A_VERY_LONG_LABEL_VALUE_THAT_EXCEEDS_SIXTY_THREE_CHARACTERS_AND_NEEDS_TRUNCATION"
    )

    additional_service = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": f"deploy-{target_entity}-{target_project}-{run_id}",
            "labels": {
                "wandb.ai/label": expected_label,
                # Add label that needs sanitization (uppercase + underscore)
                "app_label": "MY_DEPLOYMENT_LABEL_123",
            },
        },
        "spec": {
            # Add selector with matchLabels that need sanitization
            "selector": {
                "matchLabels": {
                    "app": "DEPLOY_TEST_ENTITY_TEST_PROJECT",
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        # Add pod template label that needs sanitization
                        "pod_label": "MY_POD_LABEL_456",
                    }
                },
                "spec": {
                    "containers": [
                        {
                            "name": f"pod-{target_entity}-{target_project}-{run_id}",
                        }
                    ]
                },
            },
        },
    }

    manifest["wait_for_ready"] = False

    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity=target_entity,
        target_project=target_project,
        resource_args={"kubernetes": manifest},
        launch_spec={
            "additional_services": [
                {
                    "config": additional_service,
                    "name": "additional_service",
                }
            ]
        },
        overrides={},
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri=f"https://wandb.ai/{target_entity}/{target_project}/runs/{run_id}",
        run_id=run_id,
        name="test_run",
    )

    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )

    await runner.run(project, "test_image")

    calls = mock_create_from_dict.call_args_list
    assert len(calls) == 2  # one for the main job, one for the additional service
    additional_service_call = next(
        c for c in calls if c[0][1].get("kind") == "Deployment"
    )
    assert (
        additional_service_call[0][1].get("metadata").get("name")
        == expected_deployment_name
    )

    assert (
        additional_service_call[0][1]
        .get("spec")
        .get("template")
        .get("spec")
        .get("containers")[0]
        .get("name")
        == expected_pod_name
    )

    labels = additional_service_call[0][1].get("metadata").get("labels")
    assert "wandb.ai/label" in labels
    assert labels["wandb.ai/label"] == expected_label
    assert WANDB_K8S_LABEL_AUXILIARY_RESOURCE in labels
    assert (
        labels[WANDB_K8S_LABEL_AUXILIARY_RESOURCE]
        == "123e4567-e89b-12d3-a456-426614174000"
    )

    # Verify label sanitization in additional service deployment
    # "MY_DEPLOYMENT_LABEL_123" -> "my-deployment-label-123"
    assert "app_label" in labels
    assert labels["app_label"] == "my-deployment-label-123"

    # Verify pod template label sanitization: "MY_POD_LABEL_456" -> "my-pod-label-456"
    pod_labels = (
        additional_service_call[0][1]
        .get("spec")
        .get("template")
        .get("metadata")
        .get("labels")
    )
    assert "pod_label" in pod_labels
    assert pod_labels["pod_label"] == "my-pod-label-456"

    # Verify selector matchLabels sanitization: "DEPLOY_TEST_ENTITY_TEST_PROJECT" -> "deploy-test-entity-test-project"
    selector_match_labels = (
        additional_service_call[0][1].get("spec").get("selector").get("matchLabels")
    )
    assert "app" in selector_match_labels
    assert selector_match_labels["app"] == "deploy-test-entity-test-project"

    # Verify main job labels are also sanitized
    main_job_call = next(c for c in calls if c[0][1].get("kind") == "Job")
    main_job_metadata_labels = main_job_call[0][1].get("metadata").get("labels")
    # The run_id should be sanitized if it had underscores
    assert "wandb.ai/run-id" in main_job_metadata_labels
    assert main_job_metadata_labels["wandb.ai/run-id"] == "test-run-id"

    # Verify very long label is sanitized and truncated to 63 chars
    # "THIS_IS_A_VERY_LONG_LABEL_VALUE_THAT_EXCEEDS_SIXTY_THREE_CHARACTERS_AND_NEEDS_TRUNCATION"
    # -> "this-is-a-very-long-label-value-that-exceeds-sixty-three-charac"
    assert "very_long_label" in main_job_metadata_labels
    sanitized_long_label = main_job_metadata_labels["very_long_label"]
    assert len(sanitized_long_label) == 63
    assert (
        sanitized_long_label
        == "this-is-a-very-long-label-value-that-exceeds-sixty-three-charac"
    )

    # Verify main job's pod template labels exist (they may not include run-id)
    main_job_pod_labels = (
        main_job_call[0][1].get("spec").get("template").get("metadata").get("labels")
    )
    assert main_job_pod_labels is not None
    assert "wandb.ai/monitor" in main_job_pod_labels

    # Verify environment variable names are NOT sanitized
    main_job_containers = (
        main_job_call[0][1].get("spec").get("template").get("spec").get("containers")
    )
    master_container = next(c for c in main_job_containers if c.get("name") == "master")
    env_vars = master_container.get("env", [])
    # MY_ENV_VAR should remain unchanged (not sanitized to my-env-var)
    env_var_names = [e["name"] for e in env_vars]
    assert "MY_ENV_VAR" in env_var_names
    # Make sure it wasn't sanitized
    assert "my-env-var" not in env_var_names


@pytest.mark.asyncio
async def test_runner_cleanup_on_job_creation_failure_due_to_long_name(
    monkeypatch,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    clean_agent,
    clean_monitor,
):
    """Test that auxiliary resources are cleaned up when job creation fails due to long job name."""

    # Setup mock resources to be returned by list operations
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=make_mock_resource_list(["mock-deployment"])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=make_mock_resource_list(["mock-policy"])
    )
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=make_mock_resource_list([])
    )

    # Mock helper functions
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.ensure_api_key_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_wandb_team_secrets_secret",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.ensure_initialized",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.monitor_namespace",
        MagicMock(),
    )

    # Mock create_from_dict to raise FailToCreateError simulating a long job name
    from kubernetes_asyncio.client.rest import ApiException
    from kubernetes_asyncio.utils import FailToCreateError

    async def mock_create_from_dict_failure(*args, **kwargs):
        exc = ApiException(status=422, reason="Unprocessable Entity")
        exc.body = '{"message": "Job.batch \\"test-job\\" is invalid: metadata.labels: Invalid value: must be no more than 63 characters", "code": 422}'
        raise FailToCreateError([exc])

    monkeypatch.setattr(
        "kubernetes_asyncio.utils.create_from_dict",
        mock_create_from_dict_failure,
    )

    # Create launch project WITH additional_services
    launch_project = MagicMock()
    launch_project.target_entity = "test-entity"
    launch_project.target_project = "test-project"
    launch_project.run_id = "test-run-id"
    launch_project.name = "test-name"
    launch_project.author = "test-author"
    launch_project.resource_args = {"kubernetes": {"kind": "Job"}}
    launch_project.launch_spec = {
        "_resume_count": 0,
        "additional_services": [
            {
                "config": {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "test-service"},
                }
            }
        ],
    }
    launch_project.override_args = []
    launch_project.override_entrypoint = None
    launch_project.get_single_entry_point.return_value = None
    launch_project.fill_macros = lambda image_uri: {"kubernetes": {"kind": "Job"}}
    launch_project.docker_config = {}
    launch_project.job_base_image = None
    launch_project.get_env_vars_dict = lambda _, __: {}
    launch_project.get_secrets_dict = lambda: {}

    # Create the runner
    api = MagicMock()
    environment = MagicMock()
    registry = MagicMock()
    backend_config = {"SYNCHRONOUS": False}

    runner = KubernetesRunner(api, backend_config, environment, registry)

    # Run should raise LaunchError due to job creation failure
    with pytest.raises(LaunchError, match="Failed to create Kubernetes resource"):
        await runner.run(launch_project, "test-image:latest")

    # Verify that delete methods were called for auxiliary resources
    mock_apps_api.delete_namespaced_deployment.assert_called()
    mock_network_api.delete_namespaced_network_policy.assert_called()


@pytest.mark.asyncio
async def test_runner_secrets_not_sanitized_in_secret_refs(
    monkeypatch,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    clean_agent,
    clean_monitor,
):
    """Test that secret names and keys in secretKeyRef are not sanitized."""

    # Capture the job spec passed to create_from_dict
    captured_job_spec = None

    async def mock_create_from_dict(k8s_client, yaml_objects, **kwargs):
        nonlocal captured_job_spec
        # yaml_objects can be a single dict or a list
        if isinstance(yaml_objects, dict) and yaml_objects.get("kind") == "Job":
            captured_job_spec = yaml_objects
        elif isinstance(yaml_objects, list):
            for obj in yaml_objects:
                if isinstance(obj, dict) and obj.get("kind") == "Job":
                    captured_job_spec = obj
                    break
        # Return mock response - create_from_dict returns a list of created objects
        mock_job = MagicMock()
        mock_job.metadata = MagicMock()
        mock_job.metadata.name = "test-job"
        return [mock_job]

    monkeypatch.setattr(
        "kubernetes_asyncio.utils.create_from_dict",
        mock_create_from_dict,
    )

    # Mock helper functions
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.ensure_api_key_secret",
        AsyncMock(return_value=None),
    )

    # Create a mock secret (should NOT be sanitized in refs)
    mock_secret = MagicMock()
    mock_secret.metadata = MagicMock()
    mock_secret.metadata.name = "wandb-secrets-test-run-id"
    mock_secret.metadata.namespace = "default"

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_wandb_team_secrets_secret",
        AsyncMock(return_value=mock_secret),
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.ensure_initialized",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor.monitor_namespace",
        MagicMock(),
    )

    # Create launch project with secrets that have special characters
    launch_project = MagicMock()
    launch_project.target_entity = "test-entity"
    launch_project.target_project = "test-project"
    launch_project.run_id = "test-run-id"
    launch_project.name = "test-name"
    launch_project.author = "test-author"
    launch_project.resource_args = {"kubernetes": {"kind": "Job"}}
    launch_project.launch_spec = {"_resume_count": 0}
    launch_project.override_args = []
    launch_project.override_entrypoint = None
    launch_project.get_single_entry_point.return_value = None
    launch_project.fill_macros = lambda image_uri: {"kubernetes": {"kind": "Job"}}
    launch_project.docker_config = {}
    launch_project.job_base_image = None
    launch_project.get_env_vars_dict = lambda _, __: {}

    # Secrets with underscores and uppercase - these should NOT be sanitized in secretKeyRef
    launch_project.get_secrets_dict = lambda: {
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "API_SECRET_KEY": "secret123",
        "DEBUG_MODE": "true",
    }

    # Create the runner
    api = MagicMock()
    environment = MagicMock()
    registry = MagicMock()
    backend_config = {"SYNCHRONOUS": False}

    runner = KubernetesRunner(api, backend_config, environment, registry)

    # Run the job
    submitted_run = await runner.run(launch_project, "test-image:latest")
    assert submitted_run is not None

    # Verify job spec was captured
    assert captured_job_spec is not None, "Job spec should have been captured"

    # Get the container env vars
    container_env = captured_job_spec["spec"]["template"]["spec"]["containers"][0][
        "env"
    ]

    # Verify that secretKeyRef entries exist and are NOT sanitized
    expected_secret_refs = [
        {
            "name": "DATABASE_URL",  # Should remain uppercase with underscore
            "valueFrom": {
                "secretKeyRef": {
                    "name": "wandb-secrets-test-run-id",  # Secret name unchanged
                    "key": "DATABASE_URL",  # Key should remain uppercase with underscore
                }
            },
        },
        {
            "name": "API_SECRET_KEY",  # Should remain uppercase with underscore
            "valueFrom": {
                "secretKeyRef": {
                    "name": "wandb-secrets-test-run-id",
                    "key": "API_SECRET_KEY",  # Key should remain uppercase with underscore
                }
            },
        },
        {
            "name": "DEBUG_MODE",  # Should remain uppercase with underscore
            "valueFrom": {
                "secretKeyRef": {
                    "name": "wandb-secrets-test-run-id",
                    "key": "DEBUG_MODE",  # Key should remain uppercase with underscore
                }
            },
        },
    ]

    # Verify each expected secret ref is in the container env
    for expected_ref in expected_secret_refs:
        assert expected_ref in container_env, (
            f"Expected secret ref {expected_ref} not found in container env"
        )


@pytest.mark.asyncio
@patch(
    "wandb.sdk.launch.runner.kubernetes_runner.uuid.uuid4",
    return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"),
)
async def test_resource_role_labels_on_job_and_auxiliary_resources(
    mock_uuid4,
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_maybe_create_image_pullsecret,
    mock_create_from_dict,
    test_api,
    manifest,
    clean_monitor,
    clean_agent,
):
    """Verify that Jobs get resource-role: primary and auxiliary resources get resource-role: auxiliary."""
    additional_service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "test-service"},
        "spec": {"ports": [{"port": 80}]},
    }

    manifest["wait_for_ready"] = False

    project = LaunchProject(
        docker_config={"docker_image": "test_image"},
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": manifest},
        launch_spec={
            "additional_services": [{"config": additional_service, "name": "svc"}]
        },
        overrides={},
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )

    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )

    await runner.run(project, "test_image")

    calls = mock_create_from_dict.call_args_list
    assert len(calls) == 2  # one service, one job

    job_call = next(c for c in calls if c[0][1].get("kind") == "Job")
    job_manifest = job_call[0][1]
    job_labels = job_manifest["metadata"]["labels"]

    service_call = next(c for c in calls if c[0][1].get("kind") == "Service")
    service_manifest = service_call[0][1]
    service_labels = service_manifest["metadata"]["labels"]

    # job should have resource-role: primary and NO auxiliary-resource label
    assert "wandb.ai/resource-role" in job_labels
    assert job_labels["wandb.ai/resource-role"] == "primary"
    assert "wandb.ai/auxiliary-resource" not in job_labels

    # job's pod template should also have resource-role: primary
    job_pod_labels = job_manifest["spec"]["template"]["metadata"]["labels"]
    assert "wandb.ai/resource-role" in job_pod_labels
    assert job_pod_labels["wandb.ai/resource-role"] == "primary"

    # service should have resource-role: auxiliary and auxiliary-resource UUID
    assert "wandb.ai/resource-role" in service_labels
    assert service_labels["wandb.ai/resource-role"] == "auxiliary"
    assert "wandb.ai/auxiliary-resource" in service_labels
    assert (
        service_labels["wandb.ai/auxiliary-resource"]
        == "12345678-1234-5678-1234-567812345678"
    )


def test_cleanup_manager_initialization():
    """Test that cleanup manager initializes with correct configuration."""
    # Test with defaults
    cleanup = KubernetesResourceCleanup()
    assert cleanup._minimum_age == 900
    assert "default" in cleanup._monitored_namespaces
    assert "wandb" in cleanup._monitored_namespaces

    # Test with custom values
    cleanup = KubernetesResourceCleanup(
        minimum_resource_age_seconds=600, monitored_namespaces="prod,staging,dev"
    )
    assert cleanup._minimum_age == 600
    assert cleanup._monitored_namespaces == {"prod", "staging", "dev"}


def test_cleanup_manager_namespace_parsing():
    """Test that namespace configuration is parsed correctly."""
    # Test whitespace handling
    cleanup = KubernetesResourceCleanup(monitored_namespaces=" ns1 , ns2 ,  ns3  ")
    assert cleanup._monitored_namespaces == {"ns1", "ns2", "ns3"}

    # Test empty values filtered
    cleanup = KubernetesResourceCleanup(monitored_namespaces="ns1,,ns2, ,ns3")
    assert cleanup._monitored_namespaces == {"ns1", "ns2", "ns3"}

    # Test single namespace
    cleanup = KubernetesResourceCleanup(monitored_namespaces="production")
    assert cleanup._monitored_namespaces == {"production"}


def test_cleanup_manager_environment_variable(monkeypatch):
    """Test that cleanup manager reads from environment variable."""
    monkeypatch.setenv("WANDB_LAUNCH_MONITORED_NAMESPACES", "env-ns1,env-ns2")

    cleanup = KubernetesResourceCleanup()
    assert cleanup._monitored_namespaces == {"env-ns1", "env-ns2"}


@pytest.mark.asyncio
async def test_cleanup_get_active_job_run_ids():
    """Test getting active job run-ids from Kubernetes."""
    # Create mock batch API with jobs
    mock_batch_api = MagicMock()

    # Create mock jobs with run-id labels
    mock_job1 = MagicMock()
    mock_job1.metadata.labels = {
        "wandb.ai/run-id": "run-123",
        "wandb.ai/resource-role": "primary",
    }

    mock_job2 = MagicMock()
    mock_job2.metadata.labels = {
        "wandb.ai/run-id": "run-456",
        "wandb.ai/resource-role": "primary",
    }

    mock_job3 = MagicMock()
    mock_job3.metadata.labels = {
        "wandb.ai/resource-role": "primary"
        # No run-id label
    }

    mock_list = MagicMock()
    mock_list.items = [mock_job1, mock_job2, mock_job3]
    mock_batch_api.list_namespaced_job = AsyncMock(return_value=mock_list)

    cleanup = KubernetesResourceCleanup()
    active_run_ids = await cleanup._get_active_job_run_ids(mock_batch_api, "default")

    assert active_run_ids == {"run-123", "run-456"}
    mock_batch_api.list_namespaced_job.assert_called_once_with(
        namespace="default", label_selector="wandb.ai/resource-role=primary"
    )


@pytest.mark.asyncio
async def test_cleanup_get_active_job_run_ids_with_agent_tracker(monkeypatch):
    """Test dual-source detection: Kubernetes + agent job tracker."""
    # Mock Kubernetes Jobs
    mock_batch_api = MagicMock()
    mock_job = MagicMock()
    mock_job.metadata.labels = {"wandb.ai/run-id": "run-from-k8s"}
    mock_list = MagicMock()
    mock_list.items = [mock_job]
    mock_batch_api.list_namespaced_job = AsyncMock(return_value=mock_list)

    # Mock agent returning additional run-ids (e.g., job being launched)
    mock_agent_class = MagicMock()
    mock_agent_class.initialized.return_value = True
    mock_agent_class.get_active_run_ids.return_value = {
        "run-from-agent",
        "run-launching",
    }

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.initialized",
        mock_agent_class.initialized,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.get_active_run_ids",
        mock_agent_class.get_active_run_ids,
    )

    cleanup = KubernetesResourceCleanup()
    active_run_ids = await cleanup._get_active_job_run_ids(mock_batch_api, "default")

    # Should have run-ids from BOTH sources
    assert active_run_ids == {"run-from-k8s", "run-from-agent", "run-launching"}


@pytest.mark.asyncio
async def test_cleanup_skips_aux_resources_when_job_launching(monkeypatch):
    """Test the scenario: aux resources exist, no K8s Job yet, but agent tracker has it.

    This tests the race condition window where:
    1. Agent starts launching job (in tracker)
    2. Auxiliary resources created
    3. K8s Job not yet created ← cleanup runs HERE

    Result: Should NOT delete aux resources because agent tracker has the run-id.
    """
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    # Mock Kubernetes APIs
    mock_batch_api = MagicMock()
    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()

    # NO Kubernetes Job exists yet (launching window)
    mock_batch_api.list_namespaced_job = AsyncMock(
        return_value=MagicMock(items=[])  # Empty - no Job yet!
    )

    # But agent tracker HAS this run-id (job is launching)
    mock_agent_class = MagicMock()
    mock_agent_class.initialized.return_value = True
    mock_agent_class.get_active_run_ids.return_value = {"run-launching"}

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.initialized",
        mock_agent_class.initialized,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.get_active_run_ids",
        mock_agent_class.get_active_run_ids,
    )

    # Auxiliary resources exist (old enough to clean)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_aux_service = MagicMock()
    mock_aux_service.metadata.labels = {
        "wandb.ai/run-id": "run-launching",  # Matches agent tracker!
        "wandb.ai/auxiliary-resource": "uuid-launching",
    }
    mock_aux_service.metadata.creation_timestamp = old_time
    mock_aux_service.metadata.name = "launching-service"

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=MagicMock(items=[mock_aux_service])
    )
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    # Get active run-ids (should include agent tracker)
    active_run_ids = await cleanup._get_active_job_run_ids(mock_batch_api, "default")
    assert active_run_ids == {"run-launching"}  # From agent tracker

    # Find orphaned UUIDs
    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    # CRITICAL: Should be EMPTY - resource is NOT orphaned because agent tracker has it!
    assert orphaned == set()


@pytest.mark.asyncio
async def test_cleanup_deletes_aux_resources_when_no_job_and_no_tracker(monkeypatch):
    """Test that aux resources ARE deleted when NEITHER K8s Job NOR agent tracker has the run-id.

    This is the opposite case - truly orphaned resources.
    """
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    # Mock Kubernetes APIs
    mock_batch_api = MagicMock()
    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()

    # NO Kubernetes Job exists
    mock_batch_api.list_namespaced_job = AsyncMock(return_value=MagicMock(items=[]))

    # Agent tracker does NOT have this run-id
    mock_agent_class = MagicMock()
    mock_agent_class.initialized.return_value = True
    mock_agent_class.get_active_run_ids.return_value = set()  # Empty!

    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.initialized",
        mock_agent_class.initialized,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.agent.LaunchAgent.get_active_run_ids",
        mock_agent_class.get_active_run_ids,
    )

    # Orphaned auxiliary resources exist
    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_aux_service = MagicMock()
    mock_aux_service.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-orphaned",
    }
    mock_aux_service.metadata.creation_timestamp = old_time
    mock_aux_service.metadata.name = "orphaned-service"

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=MagicMock(items=[mock_aux_service])
    )
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    # Get active run-ids (should be empty)
    active_run_ids = await cleanup._get_active_job_run_ids(mock_batch_api, "default")
    assert active_run_ids == set()  # No active jobs!

    # Find orphaned UUIDs
    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    assert orphaned == {"uuid-orphaned"}


@pytest.mark.asyncio
async def test_cleanup_get_active_job_run_ids_api_failure():
    """Test that API failure returns None (safety mechanism)."""
    mock_batch_api = MagicMock()
    mock_batch_api.list_namespaced_job = AsyncMock(
        side_effect=ApiException(status=403, reason="Forbidden")
    )

    cleanup = KubernetesResourceCleanup()
    active_run_ids = await cleanup._get_active_job_run_ids(mock_batch_api, "default")

    assert active_run_ids is None  # Returns None on failure


@pytest.mark.asyncio
async def test_cleanup_find_orphaned_uuids_basic():
    """Test finding orphaned UUIDs - basic case."""
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    # Create mock APIs
    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()

    # Mock service with orphaned UUID (old enough)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_service = MagicMock()
    mock_service.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-orphaned",
        "wandb.ai/resource-role": "auxiliary",
    }
    mock_service.metadata.creation_timestamp = old_time
    mock_service.metadata.name = "test-service"

    mock_list = MagicMock()
    mock_list.items = [mock_service]

    # Setup mock responses
    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(return_value=mock_list)
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    active_run_ids = {"run-active-1", "run-active-2"}  # run-orphaned not in here

    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    assert orphaned == {"uuid-orphaned"}


@pytest.mark.asyncio
async def test_cleanup_find_orphaned_uuids_skips_active():
    """Test that resources with active Jobs are NOT marked as orphaned."""
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_service = MagicMock()
    mock_service.metadata.labels = {
        "wandb.ai/run-id": "run-active",  # This is active
        "wandb.ai/auxiliary-resource": "uuid-123",
        "wandb.ai/resource-role": "auxiliary",
    }
    mock_service.metadata.creation_timestamp = old_time

    mock_list = MagicMock()
    mock_list.items = [mock_service]

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(return_value=mock_list)
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    active_run_ids = {"run-active"}  # run-active is active

    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    assert orphaned == set()  # Nothing orphaned - all active


@pytest.mark.asyncio
async def test_cleanup_find_orphaned_uuids_skips_recent():
    """Test that recent resources are NOT marked as orphaned (safety mechanism)."""
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()

    # Resource created 5 minutes ago (too recent - need 15 min)
    recent_time = datetime.now(timezone.utc) - timedelta(seconds=300)
    mock_service = MagicMock()
    mock_service.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-123",
        "wandb.ai/resource-role": "auxiliary",
    }
    mock_service.metadata.creation_timestamp = recent_time
    mock_service.metadata.name = "test-service"

    mock_list = MagicMock()
    mock_list.items = [mock_service]

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(return_value=mock_list)
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    active_run_ids = set()  # No active runs

    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    assert orphaned == set()  # Nothing orphaned - too recent


@pytest.mark.asyncio
async def test_cleanup_find_orphaned_uuids_multiple_resources_same_uuid():
    """Test that multiple resources with same UUID are grouped correctly."""
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()
    mock_batch_api = MagicMock()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)

    # Create multiple resources with same UUID
    mock_service = MagicMock()
    mock_service.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-shared",
    }
    mock_service.metadata.creation_timestamp = old_time
    mock_service.metadata.name = "test-service"

    mock_deployment = MagicMock()
    mock_deployment.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-shared",  # Same UUID
    }
    mock_deployment.metadata.creation_timestamp = old_time
    mock_deployment.metadata.name = "test-deployment"

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=MagicMock(items=[mock_service])
    )
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[mock_deployment])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    active_run_ids = set()

    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    # Both resources have same UUID, so only one UUID in set
    assert orphaned == {"uuid-shared"}


@pytest.mark.asyncio
async def test_cleanup_find_orphaned_uuids_missing_run_id():
    """Test that resources without run-id label are skipped."""
    cleanup = KubernetesResourceCleanup(minimum_resource_age_seconds=900)

    mock_core_api = MagicMock()
    mock_apps_api = MagicMock()
    mock_network_api = MagicMock()
    mock_batch_api = MagicMock()

    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_service = MagicMock()
    mock_service.metadata.labels = {
        # No run-id label
    }
    mock_service.metadata.creation_timestamp = old_time
    mock_service.metadata.name = "test-service"

    mock_list = MagicMock()
    mock_list.items = [mock_service]

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(return_value=mock_list)
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    active_run_ids = set()

    orphaned = await cleanup._find_orphaned_uuids(
        mock_core_api,
        mock_apps_api,
        mock_network_api,
        mock_batch_api,
        "default",
        active_run_ids,
    )

    # Resource skipped due to missing run-id
    assert orphaned == set()


@pytest.mark.asyncio
async def test_cleanup_namespace_end_to_end(
    monkeypatch,
    mock_batch_api,
    mock_core_api,
    mock_apps_api,
    mock_network_api,
    mock_kube_context_and_api_client,
):
    """Test complete cleanup flow through _cleanup_namespace including deletion."""

    # Create the mock delete function with diagnostic logging
    async def _mock_delete(*args, **kwargs):
        return None

    mock_delete = AsyncMock(side_effect=_mock_delete)

    # Patch the function at the runner module where it's accessed from
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.delete_auxiliary_resources_by_label",
        mock_delete,
    )

    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "BatchV1Api",
        lambda *args, **kwargs: mock_batch_api,
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "CoreV1Api",
        lambda *args, **kwargs: mock_core_api,
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "AppsV1Api",
        lambda *args, **kwargs: mock_apps_api,
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "NetworkingV1Api",
        lambda *args, **kwargs: mock_network_api,
    )

    # Mock active job for _get_active_job_run_ids call
    mock_job = MagicMock()
    mock_job.metadata.labels = {"wandb.ai/run-id": "run-active"}

    # Set up list_namespaced_job to handle different label selectors
    async def mock_list_jobs(namespace, label_selector=None):
        if label_selector == "wandb.ai/resource-role=primary":
            return MagicMock(items=[mock_job])
        elif label_selector == "wandb.ai/auxiliary-resource":
            return MagicMock(items=[])
        return MagicMock(items=[])

    mock_batch_api.list_namespaced_job = AsyncMock(side_effect=mock_list_jobs)

    # Mock orphaned resource
    old_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_orphaned_service = MagicMock()
    mock_orphaned_service.metadata.labels = {
        "wandb.ai/run-id": "run-orphaned",
        "wandb.ai/auxiliary-resource": "uuid-orphaned",
    }
    mock_orphaned_service.metadata.creation_timestamp = old_time
    mock_orphaned_service.metadata.name = "orphaned-service"

    mock_core_api.list_namespaced_secret = AsyncMock(return_value=MagicMock(items=[]))
    mock_core_api.list_namespaced_service = AsyncMock(
        return_value=MagicMock(items=[mock_orphaned_service])
    )
    mock_core_api.list_namespaced_pod = AsyncMock(return_value=MagicMock(items=[]))
    mock_apps_api.list_namespaced_deployment = AsyncMock(
        return_value=MagicMock(items=[])
    )
    mock_network_api.list_namespaced_network_policy = AsyncMock(
        return_value=MagicMock(items=[])
    )

    # Create cleanup instance
    cleanup = KubernetesResourceCleanup(
        minimum_resource_age_seconds=900, monitored_namespaces="test-ns"
    )

    # Run end-to-end cleanup
    await cleanup._cleanup_namespace("test-ns")

    # Verify delete was called for orphaned UUID
    assert mock_delete.called, (
        "delete_auxiliary_resources_by_label should have been called"
    )
    mock_delete.assert_called_once()
    args = mock_delete.call_args[0]
    assert args[0] == mock_apps_api
    assert args[1] == mock_core_api
    assert args[2] == mock_network_api
    assert args[3] == mock_batch_api
    assert args[4] == "test-ns"
    assert args[5] == "uuid-orphaned"


@pytest.mark.asyncio
async def test_cleanup_cycle_multiple_namespaces(monkeypatch):
    """Test that cleanup cycle processes all namespaces."""
    cleanup = KubernetesResourceCleanup(monitored_namespaces="ns1,ns2,ns3")

    cleanup_calls = []

    async def mock_cleanup_namespace(namespace):
        cleanup_calls.append(namespace)

    cleanup._cleanup_namespace = mock_cleanup_namespace

    await cleanup.run_cleanup_cycle()

    assert set(cleanup_calls) == {"ns1", "ns2", "ns3"}


@pytest.mark.asyncio
async def test_cleanup_cycle_continues_on_namespace_error(monkeypatch):
    """Test that error in one namespace doesn't stop others."""
    cleanup = KubernetesResourceCleanup(monitored_namespaces="ns1,ns2,ns3")

    cleanup_calls = []

    async def mock_cleanup_namespace(namespace):
        cleanup_calls.append(namespace)
        if namespace == "ns2":
            raise Exception("Test error in ns2")

    cleanup._cleanup_namespace = mock_cleanup_namespace

    # Should not raise - error is caught
    await cleanup.run_cleanup_cycle()

    # All three namespaces should be attempted
    assert set(cleanup_calls) == {"ns1", "ns2", "ns3"}
