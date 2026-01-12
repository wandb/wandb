from __future__ import annotations

import random

import pytest
from wandb.docker import DockerError
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    diff_pip_requirements,
    load_wandb_config,
    macro_sub,
    make_k8s_label_safe,
    parse_wandb_uri,
    pull_docker_image,
    recursive_macro_sub,
    sanitize_identifiers_for_k8s,
    validate_launch_spec_source,
    yield_containers,
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


REQUIREMENT_FILE_BASIC: list[str] = [
    "package-one==1.0.0",
    "# This is a comment in requirements.txt",
    "package-two",
    "package-three>1.0.0",
]

REQUIREMENT_FILE_BASIC_2: list[str] = [
    "package-one==2.0.0",
    "package-two>=1.0.0",
    "package-three==0.0.9",
]

REQUIREMENT_FILE_GIT: list[str] = [
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


@pytest.mark.parametrize(
    "spec,valid",
    [
        # Case 1: Valid source
        ({"job": "entity/project/job:latest"}, True),
        # Case 2: Invalid source, job and docker image specified
        (
            {"job": "entity/project/job", "docker": {"docker_image": "hello-world"}},
            False,
        ),
        # Case 3: Invalid source, empty
        (
            {},
            False,
        ),
    ],
)
def test_validate_launch_spec_source(spec, valid):
    """Test that the source is validated correctly."""
    if valid:
        validate_launch_spec_source(spec)
    else:
        with pytest.raises(LaunchError):
            validate_launch_spec_source(spec)


@pytest.mark.parametrize(
    "manifest, expected",
    [
        # Test containers key in manifest
        (
            {"containers": [{"name": "container-1"}, {"name": "container-2"}]},
            [{"name": "container-1"}, {"name": "container-2"}],
        ),
        # Test no containers key in manifest
        (
            {
                "config": {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "NetworkPolicy",
                    "metadata": {
                        "labels": {
                            "wandb.ai/label-1": "launch-agent",
                        },
                        "name": "resource-policy-${entity_name}-${project_name}-${run_id}",
                    },
                    "spec": {
                        "egress": [],
                        "podSelector": {},
                    },
                }
            },
            [],
        ),
        # Test containers key nested in spec
        (
            {
                "config": {
                    "keyShouldBeIgnored": "apps/v1",
                    "spec": {
                        "keyShouldBeIgnored": 1,
                        "template": {
                            "metadata": {
                                "labels": {
                                    "wandw.ai/label-1": "launch-agent",
                                    "wandb.ai/label-2": "${run_id}",
                                }
                            },
                            "spec": {
                                "containers": [
                                    {
                                        "image": "nicholaspun/wandb-vllm-server:v16",
                                        "ports": [{"containerPort": 8000}],
                                        "resources": {
                                            "limits": {
                                                "cpu": "10",
                                                "memory": "20G",
                                                "nvidia.com/gpu": "1",
                                            },
                                        },
                                    }
                                ],
                                "nodeSelector": {
                                    "compute.coreweave.com/node-pool": "l40"
                                },
                            },
                        },
                    },
                },
                "name": "deployment",
            },
            [
                {
                    "image": "nicholaspun/wandb-vllm-server:v16",
                    "ports": [{"containerPort": 8000}],
                    "resources": {
                        "limits": {
                            "cpu": "10",
                            "memory": "20G",
                            "nvidia.com/gpu": "1",
                        },
                    },
                },
            ],
        ),
    ],
)
def test_yield_containers(manifest, expected):
    assert list(yield_containers(manifest)) == expected


def test_make_k8s_label_safe():
    assert make_k8s_label_safe("container-1") == "container-1"  # no change needed
    assert make_k8s_label_safe("container_1") == "container-1"  # underscores to dashes
    assert (
        make_k8s_label_safe("_container_1_") == "container-1"
    )  # leading and trailing underscores removed
    assert make_k8s_label_safe("container.1") == "container1"  # dots removed
    assert make_k8s_label_safe("./*?<>:|a") == "a"  # invalid symbols removed
    assert make_k8s_label_safe("ABC123") == "abc123"  # uppercase to lowercase

    # max length & edge cases
    assert make_k8s_label_safe("a" * 65) == "a" * 63
    assert (
        make_k8s_label_safe("_" + "a" * 61 + "_" + "a") == "a" * 61
    )  # trim underscores

    # Error cases
    with pytest.raises(LaunchError):
        make_k8s_label_safe("")  # empty string raises error

    with pytest.raises(LaunchError):
        make_k8s_label_safe("--" * 64)  # only dashes raises error


@pytest.mark.parametrize(
    "manifest, expected",
    [
        # Test name in root
        ({"name": "container_1"}, {"name": "container-1"}),
        # Test name in metadata
        ({"metadata": {"name": "container_1"}}, {"metadata": {"name": "container-1"}}),
        # Test name in container
        (
            {"containers": [{"name": "container_1"}]},
            {"containers": [{"name": "container-1"}]},
        ),
        # Test name in nested container
        (
            {"nested": {"containers": [{"name": "container_1"}]}},
            {"nested": {"containers": [{"name": "container-1"}]}},
        ),
        # Test name in nested dict
        ({"nested": {"name": "container_1"}}, {"nested": {"name": "container-1"}}),
        # Test name in nested list
        (
            {"nested": [{"name": "container_1"}]},
            {"nested": [{"name": "container-1"}]},
        ),
        # Test multiple names
        (
            {"name": "container_1", "nested": {"name": "container_2"}},
            {"name": "container-1", "nested": {"name": "container-2"}},
        ),
        # Test root is list
        (
            [{"name": "container_1"}, {"name": "container_2"}],
            [{"name": "container-1"}, {"name": "container-2"}],
        ),
        # Test case with lists of primitives
        (
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": "resource-policy_jobs_1234abc",
                    "labels": {
                        "wandb.ai/created-by": "launch-agent",
                        "wandb.ai/auxiliary-resource": "aux-jobs-1234abc",
                        "wandb.ai/run-id": "1234abc",
                    },
                },
                "spec": {
                    "policyTypes": ["Ingress"],
                    "podSelector": {
                        "matchLabels": {
                            "wandb.ai/run-id": "1234abc",
                            "wandb.ai/auxiliary-resource": "aux-jobs-1234abc",
                        }
                    },
                    "ingress": [
                        {
                            "from": [
                                {
                                    "podSelector": {
                                        "matchLabels": {"job-name": "jobs-1234abc"}
                                    }
                                }
                            ],
                            "ports": [{"port": 8000, "protocol": "TCP"}],
                        }
                    ],
                },
            },
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": "resource-policy-jobs-1234abc",
                    "labels": {
                        "wandb.ai/created-by": "launch-agent",
                        "wandb.ai/auxiliary-resource": "aux-jobs-1234abc",
                        "wandb.ai/run-id": "1234abc",
                    },
                },
                "spec": {
                    "policyTypes": ["Ingress"],
                    "podSelector": {
                        "matchLabels": {
                            "wandb.ai/run-id": "1234abc",
                            "wandb.ai/auxiliary-resource": "aux-jobs-1234abc",
                        }
                    },
                    "ingress": [
                        {
                            "from": [
                                {
                                    "podSelector": {
                                        "matchLabels": {"job-name": "jobs-1234abc"}
                                    }
                                }
                            ],
                            "ports": [{"port": 8000, "protocol": "TCP"}],
                        }
                    ],
                },
            },
        ),
    ],
)
def test_sanitize_identifiers_for_k8s(manifest, expected):
    sanitize_identifiers_for_k8s(manifest)
    assert manifest == expected
