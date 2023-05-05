import pytest

from wandb.sdk.launch.runner.kubernetes_runner import add_label_to_pods, add_wandb_env


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
