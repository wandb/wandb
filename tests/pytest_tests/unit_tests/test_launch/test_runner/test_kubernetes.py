from unittest.mock import MagicMock

import pytest
import wandb
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.kubernetes_runner import (
    CrdSubmittedRun,
    KubernetesRunner,
    add_entrypoint_args_overrides,
    add_label_to_pods,
    add_wandb_env,
)


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
    env = {"TEST_ENV": "test_value", "TEST_ENV_2": "test_value_2"}
    add_wandb_env(manifest, env)
    assert manifest["spec"]["template"]["spec"]["containers"][0]["env"] == [
        {"name": "MY_ENV_VAR", "value": "MY_VALUE"},
        {"name": "TEST_ENV", "value": "test_value"},
        {"name": "TEST_ENV_2", "value": "test_value_2"},
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


def test_launch_custom(mocker, test_settings, volcano_spec):
    """Test that we can launch a custom k8s spec."""
    mock_custom_api = MagicMock()
    mock_custom_api.create_namespaced_custom_object.return_value = {
        "metadata": {"name": "test-job"}
    }
    mock_custom_api.delete_namespaced_custom_object.return_value = {
        "metadata": {"name": "test-job"}
    }
    mock_custom_api.read_namespaced_custom_object.return_value = {
        "status": {"state": "Succeeded"}
    }
    mock_custom_api.get_namespaced_custom_object_status.side_effect = [
        {"status": {"state": {"phase": "Pending"}}},
        {"status": {"state": {"phase": "Running"}}},
        {"status": {"state": {"phase": "Running"}}},
        {"status": {"state": {"phase": "Completed"}}},
    ]
    mock_core_api = MagicMock()
    mock_pod_list_response = MagicMock()
    mock_pod_list_response.items = [
        {
            "metadata": {
                "name": "test-job",
                "labels": {"app": "wandb"},
            }
        }
    ]
    mock_core_api.list_namespaced_pod.return_value = mock_pod_list_response
    mocker.patch(
        "wandb.sdk.launch.runner.kubernetes_runner.get_kube_context_and_api_client",
        return_value=(None, None),
    )
    mocker.patch(
        "wandb.sdk.launch.runner.kubernetes_runner.client.CoreV1Api",
        return_value=mock_core_api,
    )
    mocker.patch(
        "wandb.sdk.launch.runner.kubernetes_runner.client.CustomObjectsApi",
        return_value=mock_custom_api,
    )
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
        api=None,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings(), load_settings=False
    )
    runner = KubernetesRunner(api, {}, MagicMock())
    runner.wait_job_launch = MagicMock()
    submitted_run = runner.run(project, MagicMock())
    assert isinstance(submitted_run, CrdSubmittedRun)
    assert str(submitted_run.get_status()) == "starting"
    assert str(submitted_run.get_status()) == "running"
    assert submitted_run.wait()
