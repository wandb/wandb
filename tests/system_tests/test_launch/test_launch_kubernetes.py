from unittest.mock import AsyncMock, MagicMock

import kubernetes_asyncio
import pytest
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.runner import kubernetes_monitor, kubernetes_runner
from wandb.sdk.launch.utils import make_name_dns_safe


async def _mock_maybe_create_imagepull_secret(*args, **kwargs):
    pass


async def _mock_ensure_api_key_secret(*args, **kwargs):
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="This test is flaky and should be fixed")
async def test_kubernetes_run_clean_generate_name(
    use_local_wandb_backend,
    monkeypatch,
    assets_path,
):
    _ = use_local_wandb_backend

    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    entity_name = "test.@#$()entity"
    project_name = "test_\\[]project"
    expected_generate_name = make_name_dns_safe(f"launch-{entity_name}-{project_name}-")
    expected_run_name = expected_generate_name + "testname"

    setup_mock_kubernetes_client(monkeypatch, jobs, pods(expected_run_name), status)

    project = MagicMock()
    project.resource_args = {
        "kubernetes": {
            "configFile": str(assets_path("launch_k8s_config.yaml")),
        }
    }
    project.name = "testname"
    project.sweep_id = None
    project.target_entity = entity_name
    project.target_project = project_name
    project.override_config = {}
    project.override_args = ["-a", "2"]
    project.override_files = {}
    project.run_id = "testname"
    project.docker_image = "hello-world"
    project.job = "testjob"
    project.launch_spec = {"_resume_count": 0}
    project.fill_macros = lambda _: project.resource_args
    project.override_entrypoint.command = None
    project.queue_name = None
    project.queue_entity = None
    project.run_queue_item_id = None
    project.job_base_image = None

    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        runner_name="kubernetes",
        api=api,
        runner_config={"DOCKER_ARGS": {}, "SYNCHRONOUS": False},
        environment=environment,
        registry=MagicMock(),
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "maybe_create_imagepull_secret",
        _mock_maybe_create_imagepull_secret,
    )
    run = await runner.run(project, "hello-world")

    assert run.name == expected_run_name

    job = await run.batch_api.read_namespaced_job(
        name=run.name, namespace=run.namespace
    )
    assert job["metadata"]["generateName"] == expected_generate_name


@pytest.mark.skip(reason="This test is flaky and should be fixed")
@pytest.mark.asyncio
async def test_kubernetes_run_with_annotations(
    use_local_wandb_backend,
    monkeypatch,
    assets_path,
):
    _ = use_local_wandb_backend

    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        runner_name="kubernetes",
        api=api,
        runner_config={"DOCKER_ARGS": {}, "SYNCHRONOUS": False},
        environment=environment,
        registry=MagicMock(),
    )

    entity_name = "testentity"
    project_name = "testproject"
    expected_generate_name = make_name_dns_safe(f"launch-{entity_name}-{project_name}-")
    expected_run_name = expected_generate_name + "testname"

    setup_mock_kubernetes_client(monkeypatch, jobs, pods(expected_run_name), status)

    project = MagicMock()
    project.resource_args = {
        "kubernetes": {
            "configFile": str(assets_path("launch_k8s_config.yaml")),
            "metadata": {"annotations": {"x": "y"}},
        }
    }
    project.name = "testname"
    project.sweep_id = None
    project.target_entity = entity_name
    project.target_project = project_name
    project.override_config = {}
    project.override_args = ["-a", "2"]
    project.override_files = {}
    project.override_entrypoint.command = None
    project.run_id = "testname"
    project.docker_image = "hello-world"
    project.job = "testjob"
    project.fill_macros = lambda _: project.resource_args
    project.queue_name = None
    project.queue_entity = None
    project.run_queue_item_id = None
    project.job_base_image = None

    monkeypatch.setattr(
        kubernetes_runner,
        "maybe_create_imagepull_secret",
        _mock_maybe_create_imagepull_secret,
    )
    project.launch_spec = {"_resume_count": 0}
    run = await runner.run(image_uri="hello-world", launch_project=project)
    job = await run.batch_api.read_namespaced_job(
        name=run.name, namespace=run.namespace
    )
    assert job["metadata"]["generateName"] == expected_generate_name
    assert job["metadata"]["annotations"] == {"x": "y"}
    assert job["spec"]["template"]["spec"]["containers"][0]["args"] == [
        "-a",
        "2",
    ]


@pytest.mark.asyncio
async def test_kubernetes_run_env_vars(
    use_local_wandb_backend,
    monkeypatch,
    assets_path,
):
    _ = use_local_wandb_backend

    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    entity_name = "testentity"
    project_name = "testproject"
    expected_generate_name = make_name_dns_safe(f"launch-{entity_name}-{project_name}-")
    expected_run_name = expected_generate_name + "testname"

    setup_mock_kubernetes_client(monkeypatch, jobs, pods(expected_run_name), status)

    project = MagicMock()
    project.resource_args = {
        "kubernetes": {
            "configFile": str(assets_path("launch_k8s_config.yaml")),
        }
    }
    project.name = "testname"
    project.sweep_id = None
    project.target_entity = entity_name
    project.target_project = project_name
    project.override_config = {}
    project.override_args = ["-a", "2"]
    project.override_files = {}
    project.run_id = "testname"
    project.docker_image = "hello-world"
    project.job = "testjob"
    project.launch_spec = {"_resume_count": 0, "_wandb_api_key": "test-key"}
    project.fill_macros = lambda _: project.resource_args
    project.override_entrypoint.command = None
    project.queue_name = None
    project.queue_entity = None
    project.run_queue_item_id = None
    project.get_env_vars_dict = lambda _, __: {
        "WANDB_API_KEY": "test-key",
    }
    project.job_base_image = None

    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        runner_name="kubernetes",
        api=api,
        runner_config={"DOCKER_ARGS": {}, "SYNCHRONOUS": False},
        environment=environment,
        registry=MagicMock(),
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "maybe_create_imagepull_secret",
        _mock_maybe_create_imagepull_secret,
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "ensure_api_key_secret",
        _mock_ensure_api_key_secret,
    )
    monkeypatch.setattr(LaunchAgent, "initialized", lambda: True)
    monkeypatch.setattr(LaunchAgent, "name", lambda: "test-launch-agent")
    run = await runner.run(project, "hello-world")

    assert run.name == expected_run_name

    job = await run.batch_api.read_namespaced_job(
        name=run.name, namespace=run.namespace
    )

    api_key_secret = {
        "name": "WANDB_API_KEY",
        "valueFrom": {
            "secretKeyRef": {
                "name": f"wandb-api-key-{project.run_id}",
                "key": "password",
            }
        },
    }
    assert api_key_secret in job["spec"]["template"]["spec"]["containers"][0]["env"]


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


class MockBatchV1Api:
    def __init__(self, mock_api_client, jobs):
        self.jobs = jobs

    async def read_namespaced_job(self, name, namespace):
        return self.jobs[name]

    async def list_namespaced_job(self, namespace, label_selector="", **kwargs):
        ret = []
        k, v = label_selector.split("=")
        if k == "job-name":
            for job in self.jobs.items():
                if job.metadata.name == v:
                    ret.append(job)
        return MockPodList(ret)


class MockCoreV1Api:
    def __init__(self, mock_api_client, pods):
        # self.context = mock_api_client["context_name"]
        self.pods = pods
        self.namespaces = []

    async def list_namespaced_pod(self, label_selector, namespace, **kwargs):
        ret = []
        k, v = label_selector.split("=")
        if k == "job-name":
            for pod in self.pods.items:
                if pod.job_name == v:
                    ret.append(pod)
        return MockPodList(ret)

    async def create_namespace(self, body):
        self.namespaces.append(body)

    async def delete_namespace(self, name):
        self.namespaces.remove(name)


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


def setup_mock_kubernetes_client(monkeypatch, jobs, pods, mock_job_base):
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "BatchV1Api",
        lambda api_client: MockBatchV1Api(api_client, jobs),
    )
    monkeypatch.setattr(
        kubernetes_asyncio.client,
        "CoreV1Api",
        lambda api_client: MockCoreV1Api(api_client, pods),
    )
    monkeypatch.setattr(
        kubernetes_asyncio.utils,
        "create_from_dict",
        lambda _, yaml_objects, namespace: mock_create_from_dict(
            yaml_objects, jobs, mock_job_base
        ),
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_monitor.LaunchKubernetesMonitor",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.kubernetes_runner.LaunchKubernetesMonitor",
        AsyncMock(),
    )

    async def _mock_get_context_and_client(*args, **kwargs):
        return None, None

    monkeypatch.setattr(
        kubernetes_monitor,
        "get_kube_context_and_api_client",
        _mock_get_context_and_client,
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "get_kube_context_and_api_client",
        _mock_get_context_and_client,
    )

    async def mock_create_from_dict(jobd, jobs_dict, mock_status):
        name = jobd["metadata"].get("name")
        if not name:
            name = jobd["metadata"]["generateName"] + "testname"
            jobd["metadata"]["name"] = name

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
        pod_spec.node_selector = pod_spec.get("nodeSelector", {})
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
        return [mock_job]
