#!/usr/bin/env python
"""Log some images with interesting paths."""

import platform

import numpy as np

import wandb

height = width = 2
image = np.random.rand(height, width)

with wandb.init() as run:
    run.log({"normal": wandb.Image(image)})
    run.log({"with/forward/slash": wandb.Image(image)})
    try:
        run.log({"with\\backward\\slash": wandb.Image(image)})
    except ValueError:
        assert platform.system() == "Windows", "only windows throw value error"
    else:
        assert platform.system() != "Windows", "windows should have thrown value error"
