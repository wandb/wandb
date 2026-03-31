"""Integration tests for KubernetesRunner.

These tests exercise runner.run() end-to-end with mocked Kubernetes APIs,
verifying that the correct volume configuration is applied to the submitted
job manifest based on the presence/absence of PVC env vars and base image settings.
"""

import platform
from unittest.mock import MagicMock

import pytest
import wandb.sdk.launch.runner.kubernetes_runner
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.kubernetes_runner import KubernetesRunner

from .conftest import MockDict


def _make_project(test_api, resource_args, job_base_image=None, auto_default=False):
    """Build a LaunchProject for integration tests.

    When job_base_image is None, docker_image is set instead — simulating
    the case where a builder produced a pre-built image (no code mount needed).
    """
    docker_config = {} if job_base_image else {"docker_image": "built-image"}
    project = LaunchProject(
        target_entity="test_entity",
        target_project="test_project",
        resource_args={"kubernetes": resource_args},
        launch_spec={},
        overrides={},
        resource="kubernetes",
        api=test_api,
        git_info={},
        job="",
        uri="https://wandb.ai/test_entity/test_project/runs/test_run",
        run_id="test_run_id",
        name="test_run",
        docker_config=docker_config,
    )
    if job_base_image:
        project._job_artifact = MagicMock()
        project._job_artifact.name = "test_job"
        project._job_artifact.version = 0
        project.set_job_base_image(job_base_image)
        project.set_job_source_type("artifact")
        project.set_job_source_info(
            {
                "artifact_string": "test_entity/test_project/code:v0",
                "job_artifact": "test_entity/test_project/job:v0",
            }
        )
        project._auto_default_base_image = auto_default
    return project


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Launch does not support Windows.",
)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pvc_name,job_base_image,auto_default,container_command,expected_volume_type,expect_init_container,expect_dep_install",
    [
        # emptyDir cases (no PVC)
        (None, "user-image", False, None, "emptyDir", True, False),
        (None, None, False, None, None, False, False),
        (None, "pytorch", True, ["python", "train.py"], "emptyDir", True, True),
        # PVC cases
        ("wandb-source-code-pvc", "user-image", False, None, "pvc", False, False),
        ("wandb-source-code-pvc", None, False, None, None, False, False),
        (
            "wandb-source-code-pvc",
            "pytorch",
            True,
            ["python", "train.py"],
            "pvc",
            False,
            True,
        ),
    ],
    ids=[
        "emptydir-user-image",
        "emptydir-builder",
        "emptydir-auto-default",
        "pvc-user-image",
        "pvc-builder",
        "pvc-auto-default",
    ],
)
async def test_code_mount_configuration(
    pvc_name,
    job_base_image,
    auto_default,
    container_command,
    expected_volume_type,
    expect_init_container,
    expect_dep_install,
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
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner, "SOURCE_CODE_PVC_NAME", pvc_name
    )
    monkeypatch.setattr(
        wandb.sdk.launch.runner.kubernetes_runner,
        "SOURCE_CODE_PVC_MOUNT_PATH",
        str(tmpdir) if pvc_name else None,
    )
    if container_command:
        manifest["spec"]["template"]["spec"]["containers"][0]["command"] = (
            container_command
        )
    mock_batch_api.jobs = {"test-job": MockDict(manifest)}
    project = _make_project(
        test_api, manifest, job_base_image=job_base_image, auto_default=auto_default
    )
    runner = KubernetesRunner(
        test_api, {"SYNCHRONOUS": False}, MagicMock(), MagicMock()
    )

    await runner.run(project, job_base_image or "built-image")

    pod_spec = mock_create_from_dict.call_args_list[0][0][1]["spec"]["template"]["spec"]
    volumes = pod_spec.get("volumes", [])

    if expected_volume_type == "emptyDir":
        assert any(
            v.get("name") == "wandb-source-code-volume" and "emptyDir" in v
            for v in volumes
        )
        assert not any(
            v.get("name") == "wandb-source-code-volume" and "persistentVolumeClaim" in v
            for v in volumes
        )
    elif expected_volume_type == "pvc":
        assert any(
            v.get("name") == "wandb-source-code-volume" and "persistentVolumeClaim" in v
            for v in volumes
        )
        assert not any(
            v.get("name") == "wandb-source-code-volume" and "emptyDir" in v
            for v in volumes
        )
    else:
        assert not any(v.get("name") == "wandb-source-code-volume" for v in volumes)

    assert len(pod_spec.get("initContainers", [])) == (
        1 if expect_init_container else 0
    )

    main = pod_spec["containers"][0]
    if expect_dep_install:
        assert main["command"] == ["/bin/sh", "-c"]
        assert "pip install" in main["args"][0]
        assert f"exec {' '.join(container_command)}" in main["args"][0]
    elif container_command:
        assert main["command"] == container_command
