#!/usr/bin/env python
"""Use numpy in nested dict keys.

---
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config][this]: 2
  - :wandb:runs[0][config][ok]: {"3": 4}
  - :wandb:runs[0][config][deeper][again]: {"9": 34}
  - :wandb:runs[0][config][bad]: {"22": 4}
  - :wandb:runs[0][exitcode]: 0
"""

import numpy as np

import wandb

wandb.init(
    config={
        "this": 2,
        "ok": {3: 4},
        "deeper": {"again": {9: 34}},
        "bad": {np.int64(22): 4},
    }
)
