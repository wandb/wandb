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
    with pytest.raises(ValueError):
        run.log({1: 1000})
    with pytest.raises(ValueError):
        run.log({("tup", "idx"): 1000})


def test_log_not_dict(mock_run):
    run = mock_run()
    with pytest.raises(ValueError):
        run.log(10)


def test_wandb_nested_visualize(mock_run,parse_records,record_q,):
    run = mock_run()
    data = [
            ("Dog", "Dog", 34),
            ("Cat", "Cat", 29),
            ("Dog", "Cat", 5),
            ("Cat", "Dog", 3),
            ("Bird", "Bird", 40),
            ("Bird", "Cat", 2),
        ]

    logged_table = wandb.Table(columns=["Predicted", "Actual", "Count"], data=data)
    # table_name = "test2"
    print(run)
    run.log({"ramit":logged_table})
    # run.log({"test":{f"{table_name}": wandb.visualize("wandb/confusion_matrix/v1", logged_table)}})
    # run.finish()
    # parsed = parse_records(record_q)
    # print(parsed)
    assert run
    # file_record = parsed.files[0].files[0]
    # assert file_record.path == "test.rad"
