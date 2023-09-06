from wandb.sdk.launch.utils import macro_sub, recursive_macro_sub


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
