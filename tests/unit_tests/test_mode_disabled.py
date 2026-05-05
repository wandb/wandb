import pickle
import tempfile

import pytest
import wandb


def test_mode_disabled():
    """Test that the user can access all attributes of a Run object in disabled mode."""
    run = wandb.init(mode="disabled")
    symbols = [s for s in dir(run) if not s.startswith("_") and s != "log"]

    # try logging some stuff
    run.log({"a": 1})

    for symbol in symbols:
        # try accessing the attribute
        getattr(run, symbol)
        if callable(getattr(run, symbol)):
            # try calling the method
            getattr(run, symbol)()

    # disabled mode should not allow referencing attributes that don't exist
    with pytest.raises(AttributeError):
        assert run.here_s_a_twist_i_dont_exist

    with pytest.raises(AttributeError):
        assert run.me_too()


def test_disabled_run_does_not_patch_run_url_properties(mock_run):
    disabled_run = wandb.init(mode="disabled")

    assert disabled_run.project_url is None

    base_url = "https://my.cool.site.com"
    run = mock_run(
        settings=wandb.Settings(
            base_url=base_url,
            entity="me",
            project="lol",
            run_id="my-run",
        )
    )

    assert run.project_url == f"{base_url}/me/lol"


def test_disabled_can_pickle():
    # This case comes up when using wandb in disabled mode, with keras
    # https://wandb.atlassian.net/browse/WB-3981
    run = wandb.init(mode="disabled")

    with tempfile.NamedTemporaryFile() as temp_file:
        pickle.dump(run, temp_file)


def test_disabled_context_manager():
    with wandb.init(mode="disabled") as run:
        run.log({"a": 1})
        run.summary.update({"b": 2})
        run.config.update({"c": 3})
        run.log_artifact("artifact")
        run.use_artifact("artifact")
        run.log_model("model")
        run.use_model("model")
        run.link_model("model")
        run.define_metric("metric")
        run.mark_preempting()
        run.alert("alert")
