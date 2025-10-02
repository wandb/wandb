import asyncio
import base64
import json
import platform
from typing import Any
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.sdk.launch.runner.kubernetes_runner
from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiException
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.errors import LaunchError
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

    async def list_namespaced_job(self, namespace, field_selector=None):
        return [self.jobs[name] for name in self.jobs]

    async def create_job(self, body):
        self.jobs[body["metadata"]["generateName"]] = body
        return body


class MockCoreV1Api:
    def __init__(self):
        self.pods = dict()
        self.secrets = []
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
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchAgent", mock_la
    )

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
async def test_launch_additional_services(
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
    expected_auxiliary_resource_label = "aux-test-entity-test-project-test-run-id"

    additional_service = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": f"deploy-{target_entity}-{target_project}-{run_id}",
            "labels": {
                "wandb.ai/label": expected_label,
            },
        },
        "spec": {
            "template": {
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
        labels[WANDB_K8S_LABEL_AUXILIARY_RESOURCE] == expected_auxiliary_resource_label
    )
