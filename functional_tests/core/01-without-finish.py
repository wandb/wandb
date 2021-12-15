#!/usr/bin/env python
"""Base case - main process init/finish.

---
id: 0.core.01-without-finish
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
"""

import torch

import wandb
wandb.require("service")
wandb.init()
wandb.log(dict(m1=1), commit=False)
{  data:{m1:1},  commit=False }
handler:
if commit == False:
  self._internal_data.update(data)
  return

wandb.log(dict(m2=1))
self._internal_data.update(data)
dispatch() -> send to sender

{  data:{m1:1} }
wandb.log(dict(m1=1), step=100)
{  data:{m1:1},  step=100 }



wandb.log(dict(m2=2), step=200)
