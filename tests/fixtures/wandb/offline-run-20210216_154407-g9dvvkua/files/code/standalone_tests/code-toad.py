import wandb
import os

os.environ["WANDB_CODE_DIR"] = "."

wandb.init(project="code-toad")

# wandb.run.log_code()
