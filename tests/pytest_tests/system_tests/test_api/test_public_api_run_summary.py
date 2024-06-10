import pytest
import wandb


def test_delete_summary_metric_w_no_lazyload(wandb_init):
    run = wandb_init(project="test")
    run_id = run.id

    metric = "test_val"
    for i in range(10):
        run.log({metric: i})
    run.finish()

    run = wandb.Api().run(f"test/{run_id}")
    del run.summary[metric]
    run.update()

    # pytest.raises to expect a KeyError when accessing the deleted metric
    with pytest.raises(KeyError):
        _ = run.summary[metric]
