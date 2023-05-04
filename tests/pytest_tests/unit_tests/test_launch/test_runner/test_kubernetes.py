import uuid
from unittest.mock import MagicMock

from wandb.apis.internal import Api
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.kubernetes_runner import KubernetesRunner

VOLCANO_JOB = {
    "kind": "Job",
    "spec": {
        "tasks": [
            {
                "name": "master",
                "policies": [{"event": "TaskCompleted", "action": "CompleteJob"}],
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "master",
                                "image": "${image_uri}",
                                "imagePullPolicy": "IfNotPresent",
                            }
                        ],
                        "restartPolicy": "OnFailure",
                    }
                },
            },
            {
                "name": "worker",
                "replicas": 2,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "worker",
                                "image": "${image_uri}",
                                "workingDir": "/home",
                                "imagePullPolicy": "IfNotPresent",
                            }
                        ],
                        "restartPolicy": "OnFailure",
                    }
                },
            },
        ],
        "plugins": {"pytorch": ["--master=master", "--worker=worker", "--port=23456"]},
        "minAvailable": 1,
        "schedulerName": "volcano",
    },
    "metadata": {"name": f"{uuid.uuid4()}"},
    "apiVersion": "batch.volcano.sh/v1alpha1",
}


def test_kubernetes_runner(test_settings, mocker):
    api = MagicMock(Api)
    api.settings = lambda x: "test_base_url"
    runner = KubernetesRunner(api, {}, MagicMock())
    project = LaunchProject(
        uri="www.test.com",
        job="",
        api=api,
        launch_spec={"_wandb_api_key": "test_api_key"},
        target_entity="test_entity",
        target_project="test_project",
        name="test_name",
        docker_config=dict(docker_image="test_image"),
        git_info={},
        overrides={},
        resource="kubernetes",
        resource_args={"kubernetes": VOLCANO_JOB},
        run_id="test_run_id",
    )
    runner.run(project, MagicMock())
