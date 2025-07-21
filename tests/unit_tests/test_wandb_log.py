import pytest
import wandb

# ----------------------------------
# wandb.log
# ----------------------------------


def test_nice_log_error():
    with pytest.raises(wandb.Error):
        wandb.log({"no": "init"})


def test_nice_log_error_config():
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.config.update"
    ):
        wandb.config.update({"foo": 1})
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.config.foo"
    ):
        wandb.config.foo = 1


def test_nice_log_error_summary():
    with pytest.raises(
        wandb.Error,
        match=r"You must call wandb.init\(\) before wandb.summary\['great'\]",
    ):
        wandb.summary["great"] = 1
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.summary.bam"
    ):
        wandb.summary.bam = 1


def test_log_only_strings_as_keys(mock_run):
    run = mock_run()
    with pytest.raises(TypeError):
        run.log({1: 1000})
    with pytest.raises(TypeError):
        run.log({("tup", "idx"): 1000})


def test_log_not_dict(mock_run):
    run = mock_run()
    with pytest.raises(TypeError):
        run.log(10)
