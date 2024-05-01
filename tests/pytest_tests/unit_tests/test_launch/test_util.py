import random
from typing import List

import pytest
from wandb.docker import DockerError
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    diff_pip_requirements,
    load_wandb_config,
    macro_sub,
    parse_wandb_uri,
    pull_docker_image,
    recursive_macro_sub,
)


@pytest.mark.parametrize(
    "env, desired",
    [
        # Case 1; single key in single env var
        ({"WANDB_CONFIG": '{"foo": "bar"}'}, {"foo": "bar"}),
        # Case 2: multiple keys in single env var
        (
            {"WANDB_CONFIG": '{"foo": "bar", "baz": {"qux": "quux"}}'},
            {"foo": "bar", "baz": {"qux": "quux"}},
        ),
        # Case 3: multiple env vars, single key
        (
            {"WANDB_CONFIG_0": '{"foo":', "WANDB_CONFIG_1": '"bar"}'},
            {"foo": "bar"},
        ),
        # Case 4: nested, multiple config keys in multiple env vars
        (
            {
                "WANDB_CONFIG_0": '{"foo":',
                "WANDB_CONFIG_1": '"bar",',
                "WANDB_CONFIG_2": '"baz": {"qux": "quux"}}',
            },
            {"foo": "bar", "baz": {"qux": "quux"}},
        ),
    ],
)
def test_load_wandb_config(monkeypatch, env, desired):
    """Test that the wandb config is loaded correctly."""
    with monkeypatch.context() as m:
        for k, v in env.items():
            m.setenv(k, v)
        if desired is None:
            with pytest.raises(LaunchError):
                load_wandb_config()
        result = load_wandb_config()
        assert result.as_dict() == desired


def test_macro_sub():
    """Test that macros are substituted correctly."""
    string = """
    {
        "execute_image": "${wandb_image}",
        "gpu": "${wandb_gpu_count}",
        "memory": "${MY_ENV_VAR}",
        "env": {
            "WANDB_PROJECT": "${wandb_project}",
        },
    }
    """
    update_dict = {
        "wandb_image": "my-image",
        "wandb_gpu_count": "1",
        "MY_ENV_VAR": "1GB",
        "wandb_project": "test-project",
    }

    result = macro_sub(string, update_dict)
    desired = """
    {
        "execute_image": "my-image",
        "gpu": "1",
        "memory": "1GB",
        "env": {
            "WANDB_PROJECT": "test-project",
        },
    }
    """
    assert result == desired


def test_recursive_macro_sub():
    """Test that macros are substituted correctly."""
    blob = {
        "execute_image": "${wandb_image}",
        "gpu": "${wandb_gpu_count}",
        "memory": "${MY_ENV_VAR}",
        "env": [
            {"WANDB_PROJECT": "${wandb_project}"},
            {"MY_VAR": "${MY_ENV_VAR}"},
        ],
    }
    update_dict = {
        "wandb_image": "my-image",
        "wandb_gpu_count": "1",
        "MY_ENV_VAR": "1GB",
        "wandb_project": "test-project",
    }
    result = recursive_macro_sub(blob, update_dict)
    desired = {
        "execute_image": "my-image",
        "gpu": "1",
        "memory": "1GB",
        "env": [
            {"WANDB_PROJECT": "test-project"},
            {"MY_VAR": "1GB"},
        ],
    }
    assert result == desired


REQUIREMENT_FILE_BASIC: List[str] = [
    "package-one==1.0.0",
    "# This is a comment in requirements.txt",
    "package-two",
    "package-three>1.0.0",
]

REQUIREMENT_FILE_BASIC_2: List[str] = [
    "package-one==2.0.0",
    "package-two>=1.0.0",
    "package-three==0.0.9",
]

REQUIREMENT_FILE_GIT: List[str] = [
    "package-one==1.9.4",
    "git+https://github.com/path/to/package-two@41b95ec#egg=package-two",
]


def test_diff_pip_requirements():
    # Order in requirements file should not matter
    _shuffled = REQUIREMENT_FILE_BASIC.copy()
    random.shuffle(_shuffled)
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, _shuffled)
    assert not diff

    # Empty requirements file should parse fine, but appear in diff
    diff = diff_pip_requirements([], REQUIREMENT_FILE_BASIC)
    assert len(diff) == 3

    # Invalid requirements should throw LaunchError
    with pytest.raises(LaunchError):
        diff_pip_requirements(REQUIREMENT_FILE_BASIC, ["4$$%2=="])
    with pytest.raises(LaunchError):
        diff_pip_requirements(REQUIREMENT_FILE_BASIC, ["foo~~~~bar"])

    # Version mismatch should appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_BASIC_2)
    assert len(diff) == 3

    # Github package should parse fine, but appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_GIT)
    assert len(diff) == 3


def test_parse_wandb_uri_invalid_uri():
    with pytest.raises(LaunchError):
        parse_wandb_uri("invalid_uri")


def test_fail_pull_docker_image(mocker):
    mocker.patch(
        "wandb.sdk.launch.utils.docker.run",
        side_effect=DockerError("error", 1, b"", b""),
    )
    try:
        pull_docker_image("not an image")
    except LaunchError as e:
        assert "Docker server returned error" in str(e)
