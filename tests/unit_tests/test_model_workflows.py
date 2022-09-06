import tempfile

import pytest
import wandb
from wandb.beta.workflows import _add_any, use_model


def test_use_model():
    # path is an alias, must contain ":"
    with pytest.raises(ValueError):
        use_model("boom")

    # use_model can only be called in a run context, i.e after wandb.init()
    with pytest.raises(ValueError):
        use_model("boom:latest")


def test_add_any():
    artifact = wandb.Artifact(name="test-name", type="test-type")
    with tempfile.TemporaryDirectory() as tmpdir:
        _add_any(artifact, tmpdir, "temp-dir")
        with open("boom.txt", "w") as f:
            f.write("testing")

        _add_any(artifact, "boom.txt", "sample-file")
        _add_any(artifact, "non_existing_file.txt", "another-one")

        with pytest.raises(ValueError):
            _add_any(artifact, ["invalid input type"], "invalid")

    assert True


def test_offline_link_artifact(wandb_init):
    run = wandb_init(mode="offline")
    with pytest.raises(NotImplementedError):
        run.link_artifact(None, "entity/project/portfolio", "latest")
    run.finish()
