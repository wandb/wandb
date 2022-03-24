import wandb
import subprocess
import os

project_name = "multi-run-test"
if os.environ.get("WANDB_LAUNCH") is None:
    os.environ["WANDB_LAUNCH"] = "True"
if os.environ.get("WANDB_PROJECT") is None:
    os.environ["WANDB_PROJECT"] = project_name
run = wandb.init(project=project_name)
if os.environ.get("WANDB_RUN_ID") is None:
    os.environ["WANDB_RUN_ID"] = run.id
subprocess.call("./multi_run.sh", shell=True)
wandb.run.finish()
