import json
from unittest.mock import MagicMock

import kubernetes
from wandb.apis.internal import Api
from wandb.sdk.launch.builder.loader import load_builder
from wandb.sdk.launch.runner.loader import load_backend
from wandb.sdk.launch.utils import make_name_dns_safe


def test_kubernetes_run_clean_generate_name(relay_server, monkeypatch, assets_path):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    with relay_server():
        api = Api()
        runner = load_backend(
            backend_name="kubernetes",
            api=api,
            backend_config={"DOCKER_ARGS": {}, "SYNCHRONOUS": False},
        )

        entity_name = "test.@#$()entity"
        project_name = "test_\\[]project"
        expected_generate_name = make_name_dns_safe(
            f"launch-{entity_name}-{project_name}-"
        )
        expected_run_name = expected_generate_name + "testname"

        setup_mock_kubernetes_client(monkeypatch, jobs, pods(expected_run_name), status)

        project = MagicMock()
        project.resource_args = {
            "kubernetes": {
                "config_file": str(assets_path("launch_k8s_config.yaml")),
            }
        }
        project.target_entity = entity_name
        project.target_project = project_name
        project.override_config = {}
        project.job = "testjob"

        builder = load_builder({"type": "noop"})

        run = runner.run(launch_project=project, builder=builder, registry_config={})
    assert run.name == expected_run_name
    assert run.job["metadata"]["generateName"] == expected_generate_name


def test_kubernetes_run_with_annotations(relay_server, monkeypatch, assets_path):
    jobs = {}
    status = MockDict(
        {
            "succeeded": 1,
            "failed": 0,
            "active": 0,
            "conditions": None,
        }
    )

    with relay_server():
        api = Api()
        runner = load_backend(
            backend_name="kubernetes",
            api=api,
            backend_config={"DOCKER_ARGS": {}, "SYNCHRONOUS": False},
        )

        entity_name = "testentity"
        project_name = "testproject"
        expected_generate_name = make_name_dns_safe(
            f"launch-{entity_name}-{project_name}-"
        )
        expected_run_name = expected_generate_name + "testname"

        setup_mock_kubernetes_client(monkeypatch, jobs, pods(expected_run_name), status)

        job_spec = json.dumps({"metadata": {"annotations": {"x": "y"}}})

        project = MagicMock()
        project.resource_args = {
            "kubernetes": {
                "config_file": str(assets_path("launch_k8s_config.yaml")),
                "job_spec": job_spec,
            }
        }
        project.target_entity = entity_name
        project.target_project = project_name
        project.override_config = {}
        project.job = "testjob"

        builder = load_builder({"type": "noop"})

        run = runner.run(launch_project=project, builder=builder, registry_config={})
    assert run.name == expected_run_name
    assert run.job["metadata"]["generateName"] == expected_generate_name
    assert run.job["metadata"]["annotations"] == {"x": "y"}


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

    def read_namespaced_job(self, name, namespace):
        return self.jobs[name]


class MockCoreV1Api:
    def __init__(self, mock_api_client, pods):
        # self.context = mock_api_client["context_name"]
        self.pods = pods

    def list_namespaced_pod(self, label_selector, namespace):
        ret = []
        k, v = label_selector.split("=")
        if k == "job-name":
            for pod in self.pods.items:
                if pod.job_name == v:
                    ret.append(pod)
        return MockPodList(ret)


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
        lambda _, yaml_objects, namespace: mock_create_from_yaml(
            yaml_objects, jobs, mock_job_base
        ),
    )

    def mock_create_from_yaml(yaml_objects, jobs_dict, mock_status):
        jobd = yaml_objects[0]
        name = jobd["metadata"]["name"]
        if not name:
            name = jobd["metadata"]["generateName"] + "testname"

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
        return [[mock_job]]
