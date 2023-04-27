import os
from unittest.mock import MagicMock

from wandb.sdk.launch.utils import macro_sub


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
