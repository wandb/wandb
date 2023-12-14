import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import load_wandb_config, macro_sub, recursive_macro_sub


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
