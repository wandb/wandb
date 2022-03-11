import wandb
import pytest
from wandb.beta.workflows import use_model


def test_use_model():
    # path is an alias, must contain ":"
    with pytest.raises(ValueError):
        use_model("boom")

    # use_model can only be called in a run context, i.e after wandb.init()
    with pytest.raises(ValueError):
        use_model("boom:latest")
