import pytest
import wandb
import numpy


@pytest.fixture
def api(runner):
    return wandb.Api()


def test_nested_summary(api, mock_server):
    run = api.runs("test/test")[0]
    summary_dict = {"a": {"b": {"c": 0.9}}}
    summary = wandb.old.summary.Summary(run, summary_dict)
    assert summary["a"]["b"]["c"] == 0.9


def test_summary_setitem(api, mock_server):
    img = np.random.random((100, 100))
    run = api.runs("test/test")[0]
    run.summary["acc2"] = run.summary["acc"]
    run.summary["img"] = wandb.Image(img)
    run.summary.update()
