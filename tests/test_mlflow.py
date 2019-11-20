import mlflow
import wandb
import os
import json
from wandb import env
from .utils import git_repo


def test_basic_mlflow(live_mock_server, git_repo):
    os.environ[env.BASE_URL] = "http://localhost:%i" % 8765
    os.environ[env.API_KEY] = "a" * 40
    with mlflow.start_run():
        mlflow.log_param("test_param", 5)

        # Log a metric; metrics can be updated throughout the run
        mlflow.log_metric("acc", 1, 1)
        mlflow.log_metric("acc", 2, 2)
        mlflow.log_metric("acc", 3, 3)

        with open("output.txt", "w") as f:
            f.write("Hello world!")
        mlflow.log_artifact("output.txt")
    history = [json.loads(r) for r in open(os.path.join(wandb.run.dir, "wandb-history.jsonl")).readlines()]
    assert len(history) == 3
    assert wandb.run.config["test_param"] == 5
    assert os.path.exists(os.path.join(wandb.run.dir, "output.txt"))
