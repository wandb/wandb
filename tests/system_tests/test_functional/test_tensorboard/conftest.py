import pytest
import wandb


@pytest.fixture(autouse=True)
def unpatch_tensorboard():
    yield

    # Undo any TensorBoard patching after every test in this directory
    # to prevent order dependence.
    wandb.tensorboard.unpatch()
