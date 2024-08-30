#!/usr/bin/env python
"""Base case - logging sequence of media types multiple times.

---
id: 0.core.05-log-media
plugin:
    - wandb
    - numpy
depend:
  requirements:
    - pillow
tag:
  skips:
    - platform: win
assert:
    - :wandb:runs_len: 1
    - :wandb:runs[0][config]: {}
    - :wandb:runs[0][summary][media][count]: 2
    - :wandb:runs[0][summary][media][_type]: images/separated
    - :wandb:runs[0][summary][media][format]: png
    - :wandb:runs[0][summary][media][height]: 2
    - :wandb:runs[0][summary][media][width]: 2
    - :wandb:runs[0][exitcode]: 0
"""

import numpy as np

import wandb

height = width = 2

run = wandb.init()
media = []
for image in [np.random.rand(height, width) for _ in range(2)]:
    media.append(wandb.Image(image))
    run.log({"media": media}, commit=False)
