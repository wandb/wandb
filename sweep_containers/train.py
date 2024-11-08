import wandb

import os
import json
import time


config = json.loads(os.environ["CONFIG"])


run = wandb.init(resume="allow", job_type="train", config=config)


x = run.config["x"]
y = run.config["y"]
for i in range(0,100):
    print(f"iteration {i}")
    run.log({"loss": x*y*i})
    time.sleep(1)
