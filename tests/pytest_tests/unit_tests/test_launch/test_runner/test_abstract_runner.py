import os
from unittest.mock import MagicMock

from wandb.sdk.launch.runner.abstract import AbstractRunner


class TestRunner(AbstractRunner):
    """Runner used to test behavior of the base class."""

    def __init__(self) -> None:
        """Initialize the test runner."""
        super().__init__(MagicMock(), MagicMock())

    def run(self, *args, **kwargs) -> None:
        """Dummy run method for testing."""
        pass


def test_macro_sub():
    """Test that macros are substituted correctly."""
    project = MagicMock()
    project.resource_args = {
        "image": "${wandb_image}",
        "memory": "1GB",
        "gpu": "${MY_VAR}",
        "env": {"FOO": "${wandb_project}"},
    }
    project.target_project = "test-project"
    project.target_entity = "test-entity"
    project.run_id = "test-run-id"
    project.run_name = "test-run-name"
    image = "test-image"
    os.environ["MY_VAR"] = "my-value"

    runner = TestRunner()
    args = runner._fill_macros(project, image)
    assert args == {
        "image": image,
        "memory": "1GB",
        "gpu": "my-value",
        "env": {"FOO": "test-project"},
    }
