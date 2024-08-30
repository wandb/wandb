import tempfile

import pytest
import wandb
from wandb.beta.workflows import _add_any, use_model


def test_use_model():
    # path is an alias, must contain ":"
    with pytest.raises(ValueError):
        use_model("wandb")

    # use_model can only be called in a run context, i.e after wandb.init()
    with pytest.raises(ValueError):
        use_model("wandb:latest")


def test_add_any():
    artifact = wandb.Artifact(name="test-name", type="test-type")
    with tempfile.TemporaryDirectory() as tmpdir:
        _add_any(artifact, tmpdir, "temp-dir")
        with open("wandb.txt", "w") as f:
            f.write("testing")

        _add_any(artifact, "wandb.txt", "sample-file")
        _add_any(artifact, "non_existing_file.txt", "another-one")

        with pytest.raises(ValueError):
            _add_any(artifact, ["invalid input type"], "invalid")
