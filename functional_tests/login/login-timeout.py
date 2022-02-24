#!/usr/bin/env python
"""Test stdin timeout
---
id: 0.login.1-timeout
plugin:
  - wandb
tag:
  skips:
    - platform: win
assert:
  - :yea:exit: 0
"""

import time

import wandb


timeout = 4
slop = 0.50
tm_start = time.time()
result = wandb.login(timeout=timeout, relogin=True)
tm_elapsed = time.time() - tm_start
print(f"time elapsed: {tm_elapsed}")
print(f"result: {result}")
assert tm_elapsed < timeout * (1 + slop)
assert result is False
