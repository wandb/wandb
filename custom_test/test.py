import os

if "WANDV_DIR" in os.environ:
    del(os.environ["WANDB_ENV"])

os.environ["WANDB_DIR"] = os.path.join(os.getcwd(), "env_custom")
print(os.environ["WANDB_DIR"])
if not os.path.isdir(os.environ["WANDB_DIR"]):
    os.makedirs(os.environ["WANDB_DIR"])

import wandb

wandb.init()
# wandb.init(dir="dir_custom")
print("done")
print(os.listdir(os.getcwd()))
