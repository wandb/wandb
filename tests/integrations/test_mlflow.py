import mlflow
import wandb
import os
import json
from wandb import env


def test_basic_mlflow(live_mock_server, git_repo, parse_ctx):
    os.environ[env.BASE_URL] = live_mock_server.base_url
    os.environ[env.API_KEY] = "a" * 40
    wandb.mlflow.patch()
    wandb_run = None
    with mlflow.start_run():
        mlflow.log_param("test_param", 5)

        # Log a metric; metrics can be updated throughout the run
        mlflow.log_metric("acc", 1, 1)
        mlflow.log_metric("acc", 2, 2)
        mlflow.log_metric("acc", 3, 3)

        with open("output.txt", "w") as f:
            f.write("Hello world!")
        wandb_run = wandb.run
        mlflow.log_artifact("output.txt")
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    summary = ctx_util.summary
    history = ctx_util.history
    config = ctx_util.config
    assert len(history) == 3
    assert config["test_param"]["value"] == 5
    assert summary["acc"] == 3
    # TODO: make artifacts log artifacts
    assert os.path.exists(os.path.join(wandb_run.dir, "output.txt"))