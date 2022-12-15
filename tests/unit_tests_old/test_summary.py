import pytest
import wandb


@pytest.fixture
def api(runner):
    return wandb.Api()


def test_nested_summary(api, mock_server):
    run = api.runs("test/test")[0]
    summary_dict = {"a": {"b": {"c": 0.9}}}
    summary = wandb.old.summary.Summary(run, summary_dict)
    assert summary["a"]["b"]["c"] == 0.9
