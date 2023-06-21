"""Base case - logging sequence of media types multiple times."""

import numpy as np
import wandb

height = width = 2

run = wandb.init()
media = []
for image in [np.random.rand(height, width) for _ in range(2)]:
    media.append(wandb.Image(image))
    run.log({"media": media}, commit=False)
