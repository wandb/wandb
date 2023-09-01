import base64
import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.kubernetes_runner import (
    CrdSubmittedRun,
    KubernetesRunMonitor,
    KubernetesRunner,
    add_entrypoint_args_overrides,
    add_label_to_pods,
    add_wandb_env,
    maybe_create_imagepull_secret,
)


def blink():
    """Sleep for a short time to allow the thread to run."""
    time.sleep(0.1)


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

    def __iter__(self):
        while True:
            while not self.queue:
                time.sleep(0.05)
            yield self.queue.pop(0)

    def add(self, event: Any):
        self.queue.append(event)


class MockBatchApi:
    """Mocks a kubernetes batch API client."""

    def __init__(self):
        self.jobs = dict()

    def read_namespaced_job(self, name, namespace):
        return self.jobs[name]

    def read_namespaced_job_status(self, name, namespace):
        return self.jobs[name]

    def patch_namespaced_job(self, name, namespace, body):
        if body.spec.suspend:
            self.jobs[name].status.conditions = [MockDict({"type": "Suspended"})]
            self.jobs[name].status.active -= 1

    def delete_namespaced_job(self, name, namespace):
        del self.jobs[name]

    def list_namespaced_job(self, namespace, field_selector=None):
        return [self.jobs[name] for name in self.jobs]


class MockCoreV1Api:
    def __init__(self):
        self.pods = dict()

    def list_namespaced_pod(
        self, label_selector=None, namespace="default", field_selector=None
    ):
        ret = []
        for _, pod in self.pods.items():
            ret.append(pod)
        return MockPodList(ret)

    def read_namespaced_pod(self, name, namespace):
        return self.pods[name]

    def delete_namespaced_secret(self, namespace, name):
        pass


class MockCustomObjectsApi:
    def __init__(self):
        self.jobs = dict()

    def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        self.jobs[body["metadata"]["name"]] = body
        return body

    def delete_namespaced_custom_object(
        self, group, version, namespace, plural, name, body
    ):
        del self.jobs[name]

    def read_namespaced_custom_object(
        self, group, version, namespace, plural, name, body
    ):
        return self.jobs[name]

    def get_namespaced_custom_object_status(
        self, group, version, namespace, plural, name, body
    ):
        return self.jobs[name]

    def list_namespaced_custom_object(
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
        "wandb.sdk.launch.runner.kubernetes_runner.watch.Watch.stream",
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
    mock_api_client = {"context_name": "test-context"}
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.get_kube_context_and_api_client",
        lambda *args, **kwargs: (None, None),
    )
    return mock_api_client


@pytest.fixture
def mock_create_from_yaml(monkeypatch):
    """Patches the kubernetes create_from_yaml with a mock and returns it."""
    function_mock = MagicMock()
    function_mock.return_value = [
        [MockDict({"metadata": MockDict({"name": "test-job"})})]
    ]
    monkeypatch.setattr(
        "kubernetes.utils.create_from_yaml",
        function_mock,
    )
    return function_mock


def test_launch_kube_works(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_create_from_yaml,
    test_api,
    manifest,
):
    """Test that we can launch a kubernetes job."""
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_imagepull_secret",
        lambda *args, **kwargs: None,
    )
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
    runner.wait_job_launch = MagicMock()
    submitted_run = runner.run(project, MagicMock())

    def _wait():
        submitted_run.wait()

    thread = threading.Thread(target=_wait, daemon=True)
    thread.start()
    blink()
    assert str(submitted_run.get_status()) == "starting"
    job_stream, pod_stream = mock_event_streams
    pod_stream.add(
        MockDict(
            {
                "type": "ADDED",
                "object": MockDict(
                    {
                        "metadata": MockDict({"name": "test-pod"}),
                        "status": MockDict({"phase": "Pending"}),
                    }
                ),
            }
        )
    )
    blink()
    assert str(submitted_run.get_status()) == "starting"
    job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": MockDict(
                    {
                        "metadata": MockDict({"name": "test-job"}),
                        "status": MockDict({"succeeded": 1}),
                    }
                ),
            }
        )
    )
    blink()
    assert str(submitted_run.get_status()) == "finished"
    thread.join()

    assert mock_create_from_yaml.call_count == 1
    submitted_manifest = mock_create_from_yaml.call_args_list[0][1]["yaml_objects"][0]
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


def test_launch_crd_works(
    monkeypatch,
    mock_event_streams,
    mock_batch_api,
    mock_custom_api,
    mock_kube_context_and_api_client,
    mock_create_from_yaml,
    test_api,
    volcano_spec,
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
    runner.wait_job_launch = MagicMock()
    submitted_run = runner.run(project, MagicMock())

    def _wait():
        submitted_run.wait()

    thread = threading.Thread(target=_wait, daemon=True)
    thread.start()
    blink()
    assert str(submitted_run.get_status()) == "starting"
    job_stream, pod_stream = mock_event_streams
    # add container creating event
    pod_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": MockDict({"status": MockDict({"phase": "Running"})}),
            }
        )
    )
    blink()
    assert str(submitted_run.get_status()) == "running"
    job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": MockDict(
                    {
                        "metadata": MockDict({"name": "test-job"}),
                        "status": {"state": {"phase": "Succeeded"}},
                    }
                ),
            }
        )
    )
    blink()
    assert str(submitted_run.get_status()) == "finished"
    thread.join()


@pytest.mark.timeout(320)
def test_launch_kube_failed(
    monkeypatch,
    mock_batch_api,
    mock_kube_context_and_api_client,
    mock_create_from_yaml,
    mock_event_streams,
    test_api,
    manifest,
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
    runner.wait_job_launch = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.maybe_create_imagepull_secret",
        lambda *args, **kwargs: None,
    )
    job_stream, pod_stream = mock_event_streams
    job_stream.add(
        MockDict(
            {
                "type": "MODIFIED",
                "object": MockDict(
                    {
                        "metadata": MockDict({"name": "test-job"}),
                        "status": MockDict({"failed": 1}),
                    }
                ),
            }
        )
    )
    submitted_run = runner.run(project, MagicMock())
    submitted_run.wait()
    assert str(submitted_run.get_status()) == "failed"


def test_maybe_create_imagepull_secret_given_creds():
    mock_registry = MagicMock()
    mock_registry.get_username_password.return_value = ("testuser", "testpass")
    mock_registry.uri = "test.com"
    api = MagicMock()
    maybe_create_imagepull_secret(
        api,
        mock_registry,
        "12345678",
        "wandb",
    )
    namespace, secret = api.create_namespaced_secret.call_args[0]
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


# Test monitor class.


def job_factory(statuses):
    """Factory for creating job events."""
    return MockDict(
        {
            "object": MockDict(
                {"status": MockDict({f"{status}": 1 for status in statuses})}
            ),
        }
    )


def pod_factory(event_type, condition_types, condition_reasons, phase=None):
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
            "object": MockDict(
                {
                    "status": MockDict(
                        {
                            "phase": phase,
                            "conditions": [
                                MockDict(
                                    {
                                        "type": condition_type,
                                        "reason": condition_reason,
                                    }
                                )
                                for condition_type, condition_reason in zip(
                                    condition_types, condition_reasons
                                )
                            ],
                        }
                    ),
                }
            ),
        }
    )


@pytest.mark.parametrize(
    "reason",
    ["EvictionByEvictionAPI", "PreemptionByScheduler", "TerminationByKubelet"],
)
def test_monitor_preempted(mock_event_streams, mock_batch_api, mock_core_api, reason):
    """Test if the monitor thread detects a preempted job."""
    monitor = KubernetesRunMonitor(
        job_field_selector="foo=bar",
        pod_label_selector="foo=bar",
        batch_api=mock_batch_api,
        core_api=mock_core_api,
        namespace="wandb",
    )
    monitor.start()
    _, pod_event_stream = mock_event_streams
    pod_event_stream.add(pod_factory("ADDED", [], []))
    blink()
    pod_event_stream.add(pod_factory("MODIFIED", ["DisruptionTarget"], [reason]))
    blink()
    assert monitor.get_status().state == "preempted"


def test_monitor_succeeded(mock_event_streams, mock_batch_api, mock_core_api):
    """Test if the monitor thread detects a succeeded job."""
    monitor = KubernetesRunMonitor(
        job_field_selector="foo=bar",
        pod_label_selector="foo=bar",
        batch_api=mock_batch_api,
        core_api=mock_core_api,
        namespace="wandb",
    )
    monitor.start()
    job_event_stream, pod_event_stream = mock_event_streams
    blink()
    pod_event_stream.add(pod_factory("ADDED", [], []))
    blink()
    job_event_stream.add(job_factory(["succeeded"]))
    blink()
    assert monitor.get_status().state == "finished"


def test_monitor_failed(mock_event_streams, mock_batch_api, mock_core_api):
    """Test if the monitor thread detects a failed job."""
    monitor = KubernetesRunMonitor(
        job_field_selector="foo=bar",
        pod_label_selector="foo=bar",
        batch_api=mock_batch_api,
        core_api=mock_core_api,
        namespace="wandb",
    )
    monitor.start()
    job_event_stream, pod_event_stream = mock_event_streams
    blink()
    pod_event_stream.add(pod_factory("ADDED", [], []))
    blink()
    job_event_stream.add(job_factory(["failed"]))
    blink()
    assert monitor.get_status().state == "failed"


def test_monitor_running(mock_event_streams, mock_batch_api, mock_core_api):
    """Test if the monitor thread detects a running job."""
    monitor = KubernetesRunMonitor(
        job_field_selector="foo=bar",
        pod_label_selector="foo=bar",
        batch_api=mock_batch_api,
        core_api=mock_core_api,
        namespace="wandb",
    )
    monitor.start()
    job_event_stream, pod_event_stream = mock_event_streams
    blink()
    pod_event_stream.add(pod_factory("ADDED", [], []))
    blink()
    job_event_stream.add(job_factory(["active"]))
    blink()
    pod_event_stream.add(pod_factory("MODIFIED", [""], [""], phase="Running"))
    blink()
    assert monitor.get_status().state == "running"
