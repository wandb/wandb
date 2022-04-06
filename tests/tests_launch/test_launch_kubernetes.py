import json
import os
import subprocess
from unittest.mock import MagicMock

import kubernetes
import wandb
from wandb.errors import LaunchError
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.runner.kubernetes import KubernetesRunner, MAX_KUBERNETES_RETRIES
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
        self.context = mock_api_client["context_name"]
        self.jobs = jobs

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


class MockCoreV1Api(object):
    def __init__(self, mock_api_client, pods):
        self.context = mock_api_client["context_name"]
        self.pods = pods

    def list_namespaced_pod(self, label_selector, namespace):
        ret = []
        k, v = label_selector.split("=")
        if k == "job-name":
            for pod in self.pods.items:
                if pod.job_name == v:
                    ret.append(pod)
        return MockPodList(ret)

    def read_namespaced_pod_log(self, name, namespace):
        for pod in self.pods.items:
            if pod.metadata.name == name:
                return pod.log


def setup_mock_kubernetes_client(monkeypatch, jobs, pods, mock_job_base):
    mock_contexts = [
        {"name": "active-context", "context": {"namespace": "active-namespace"}},
        {"name": "inactive-context", "context": {"namespace": "inactive-namespace"}},
    ]

    def mock_api_config(context):
        return {
            "context_name": context,
        }

    def mock_create_from_yaml(
        api_client, yaml_objects, namespace, jobs_dict, mock_status
    ):
        jobd = yaml_objects[0]
        name = jobd["metadata"]["name"]
        if not name:
            name = jobd["metadata"]["generateName"] + "asdfasdf"

        metadata = MockDict(jobd["metadata"])
        metadata.labels = metadata.get("labels", {})
        metadata.labels["job-name"] = name  # assign name
        job_spec = MockDict(jobd["spec"])
        job_spec.backoff_limit = job_spec.get("backoffLimit", 6)  # kube defaults
        job_spec.completions = job_spec.get("completions", 1)
        job_spec.parallelism = job_spec.get("parallelism", 1)
        job_spec.suspend = job_spec.get("suspend", False)
        pod_spec = MockDict(jobd["spec"]["template"]["spec"])
        pod_spec.restart_policy = pod_spec.get("restartPolicy", "Never")
        pod_spec.preemption_policy = pod_spec.get(
            "preemptionPolicy", "PreemptLowerPriority"
        )
        pod_spec.node_name = pod_spec.get("nodeName", None)
        pod_spec.node_selector = pod_spec.get("nodeSelectors", {})
        pod_spec.containers = pod_spec.get("containers")
        for i, cont in enumerate(pod_spec.containers):
            pod_spec.containers[i] = MockDict(cont)

        job_spec.template = MockDict(
            {
                "spec": pod_spec,
            }
        )
        mock_job = MockDict(
            {
                "status": mock_status,
                "spec": job_spec,
                "metadata": MockDict(metadata),
            }
        )
        jobs_dict[name] = mock_job
        return [[mock_job]]

    monkeypatch.setattr(
        kubernetes.config,
        "list_kube_config_contexts",
        lambda config_file: (mock_contexts, mock_contexts[0]),
    )
    monkeypatch.setattr(
        kubernetes.config,
        "new_client_from_config",
        lambda config_file, context: mock_api_config(context),
    )
    monkeypatch.setattr(kubernetes.config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(
        kubernetes.client.api_client, "ApiClient", lambda: mock_api_config(None)
    )
    monkeypatch.setattr(
        kubernetes.config, "load_kube_config", lambda config_file, context_name: None
    )
    monkeypatch.setattr(
        kubernetes.client,
        "BatchV1Api",
        lambda api_client: MockBatchV1Api(api_client, jobs),
    )
    monkeypatch.setattr(
        kubernetes.client,
        "CoreV1Api",
        lambda api_client: MockCoreV1Api(api_client, pods),
    )
    monkeypatch.setattr(
        kubernetes.utils,
        "create_from_yaml",
        lambda api_client, yaml_objects, namespace: mock_create_from_yaml(
            api_client, yaml_objects, namespace, jobs, mock_job_base
        ),
    )

    monkeypatch.setattr(
        "wandb.docker.push",
        lambda repo, tag: None,
    )


def pods(job_name):
    return MockPodList(
        [
            MockDict(
                {
                    "metadata": MockDict(
                        {
                            "name": "pod1",
                        }
                    ),
                    "job_name": job_name,
                    "log": "test log string",
                }
            )
        ]
    )


@pytest.mark.timeout(320)
def test_launch_kube(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("test-job"), status)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    multi_spec = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "container1",
                        },
                        {
                            "name": "container2",
                        },
                    ]
                }
            }
        }
    }

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "kubernetes",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {
            "kubernetes": {
                "job_spec": json.dumps(multi_spec),
                "config_file": "dummy.yaml",
                "registry": "test.registry",
                "job_name": "test-job",
                "job_labels": {"test-label": "test-val"},
                "backoff_limit": 3,
                "completions": 4,
                "parallelism": 5,
                "restart_policy": "OnFailure",
                "preemption_policy": "Never",
                "node_name": "test-node-name",
                "node_selectors": {"test-selector": "test-value"},
            },
        },
    }

    with pytest.raises(LaunchError) as e:
        run = launch.run(**kwargs)
        assert "Launch only builds one container at a time" in str(e.value)
    del kwargs["resource_args"]["kubernetes"]["job_spec"]

    run = launch.run(**kwargs)
    assert run.id == "test-job"
    assert run.namespace == "active-namespace"
    assert run.pod_names == ["pod1"]
    assert run.get_status().state == "finished"
    assert run.wait()
    job = run.get_job()
    args = kwargs["resource_args"]["kubernetes"]
    assert job.metadata.labels["test-label"] == args["job_labels"]["test-label"]
    assert job.spec.backoff_limit == args["backoff_limit"]
    assert job.spec.completions == args["completions"]
    assert job.spec.parallelism == args["parallelism"]
    assert job.spec.template.spec.restart_policy == args["restart_policy"]
    assert job.spec.template.spec.preemption_policy == args["preemption_policy"]
    assert job.spec.template.spec.node_name == args["node_name"]
    assert (
        job.spec.template.spec.node_selector["test-selector"]
        == args["node_selectors"]["test-selector"]
    )
    container = job.spec.template.spec.containers[0]
    assert "test.registry/" in container.image
    out, err = capsys.readouterr()
    assert "Job test-job created on pod(s) pod1" in err


@pytest.mark.timeout(320)
def test_launch_kube_suspend_cancel(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 0,
            "failed": 0,
            "active": 1,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("launch-asdfasdf"), status)

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
                "config_file": "dummy.yaml",
                "suspend": False,
            },
        },
        "synchronous": False,
    }
    run = launch.run(**kwargs)
    assert run.get_status().state == "running"
    run.suspend()

    assert run.id == "launch-asdfasdf"
    assert run.namespace == "active-namespace"
    assert run.pod_names == ["pod1"]
    assert run.get_status().state == "stopped"

    run.cancel()

    with pytest.raises(KeyError):
        run.get_status()


@pytest.mark.timeout(320)
def test_launch_kube_failed(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 0,
            "failed": 1,
            "active": 0,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("launch-asdfasdf"), status)

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
        "resource_args": {},
    }
    run = launch.run(**kwargs)

    assert run.id == "launch-asdfasdf"
    assert run.pod_names == ["pod1"]
    assert run.get_status().state == "failed"
    out, err = capsys.readouterr()
    assert "Note: no resource args specified" in err


def test_set_context(live_mock_server, test_settings, monkeypatch):
    setup_mock_kubernetes_client(monkeypatch, {}, pods("test"), MockDict({}))
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    runner = KubernetesRunner(api, {})

    resource_args = {}
    context = runner._set_context(kubernetes, None, resource_args)
    assert context["name"] == "active-context"

    resource_args = {
        "context": "inactive-context",
    }
    context = runner._set_context(kubernetes, None, resource_args)
    assert context["name"] == "inactive-context"

    resource_args = {
        "context": "context-not-found",
    }
    with pytest.raises(LaunchError) as e:
        runner._set_context(kubernetes, None, resource_args)
        assert "Specified context context-not-found was not found" in str(e.value)


@pytest.mark.timeout(320)
def test_kube_user_container(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("launch-asdfasdf"), status)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    multi_spec = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "image": "container1:tag",
                        },
                        {
                            "image": "container2:tag",
                        },
                    ]
                }
            }
        }
    }

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "kubernetes",
        "entity": "mock_server_entity",
        "project": "test",
        "docker_image": "test:tag",
        "config": {"docker": {"args": {"test-arg": "unused"}}},
        "resource_args": {"kubernetes": {"job_spec": json.dumps(multi_spec)}},
    }
    with pytest.raises(LaunchError) as e:
        run = launch.run(**kwargs)
        assert "Multiple container configurations should be specified" in str(e.value)
    del kwargs["resource_args"]["kubernetes"]["job_spec"]

    run = launch.run(**kwargs)
    out, err = capsys.readouterr()
    assert "Docker args are not supported for Kubernetes" in err
    job = run.get_job()
    container = job.spec.template.spec.containers[0]
    assert container.image == "test:tag"
    assert "WANDB_RUN_ID" not in [ev["name"] for ev in container.env]


@pytest.mark.timeout(320)
def test_kube_multi_container(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("launch-asdfasdf"), status)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    spec = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "image": "container1:tag",
                        },
                        {
                            "image": "container2:tag",
                        },
                    ]
                }
            }
        }
    }
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "kubernetes",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {
            "kubernetes": {
                "job_spec": json.dumps(spec),
                "container_name": "broken-name",
            }
        },
    }
    kwargs["docker_image"] = "test:tag"
    with pytest.raises(LaunchError) as e:
        run = launch.run(**kwargs)
        assert "Multiple container configurations should be specified in a yaml" in str(
            e.value
        )
    del kwargs["docker_image"]

    with pytest.raises(LaunchError) as e:
        run = launch.run(**kwargs)
        assert "Container name override not supported for multiple containers" in str(
            e.value
        )

    del kwargs["resource_args"]["kubernetes"]["container_name"]
    kwargs["resource_args"]["kubernetes"]["resource_requests"] = {"cpu": 1}

    run = launch.run(**kwargs)
    out, err = capsys.readouterr()
    assert (
        "Container overrides (e.g. resource limits) were provided with multiple containers specified"
        in err
    )
    job = run.get_job()
    container1 = job.spec.template.spec.containers[0]
    assert container1.image == "container1:tag"
    assert container1.resources["requests"]["cpu"] == 1
    container2 = job.spec.template.spec.containers[1]
    assert container2.image == "container2:tag"
    assert container2.resources["requests"]["cpu"] == 1


@pytest.mark.timeout(320)
def test_get_status_failed(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch, capsys
):
    def read_namespaced_pod_log_error(c, name, namespace):
        raise Exception("test read_namespaced_pod_log_error")

    jobs = {}
    status = MockDict(
        {
            "succeeded": 0,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    setup_mock_kubernetes_client(monkeypatch, jobs, pods("launch-asdfasdf"), status)

    monkeypatch.setattr(
        MockCoreV1Api, "read_namespaced_pod_log", read_namespaced_pod_log_error
    )

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
        "resource_args": {"kubernetes": {}},
        "synchronous": False,
    }

    run = launch.run(**kwargs)
    run.get_status()  # fail count => 1
    out, err = capsys.readouterr()
    assert "Failed to get pod status for job" in err

    run._fail_count = MAX_KUBERNETES_RETRIES
    with pytest.raises(LaunchError) as e:
        status = run.get_status()
        assert "Failed to start job" in str(e.value)
