import wandb
import random
import time
import numpy as np

wandb.init(project="test-windows")
for i in range(100):
    print("Loop %i" % i)
    wandb.log({"acc": random.random(), "image": wandb.Image(np.random.randint(0, 255, (28,28)))})
    time.sleep(0.3)