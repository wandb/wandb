import argparse

import wandb

parser = argparse.ArgumentParser()
parser.add_argument("--log-test", action="store_true")
args = parser.parse_args()
run = wandb.init(project="test-job", config={"foo": "bar", "lr": 0.1, "epochs": 5})
for i in range(1, run.config["epochs"]):
    wandb.log({"loss": i})
if args.log_test:
    wandb.log({"test_loss": i})
run.finish()
