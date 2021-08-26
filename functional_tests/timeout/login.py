#!/usr/bin/env python
"""Test stdin timeout

---
id: 0.timeout.2
"""

import time

import wandb


timeout = 4
slop = 0.50
tm_start = time.time()
wandb.login(timeout=timeout, relogin=True)
tm_elapsed = time.time() - tm_start
print(f"time elapsed: {tm_elapsed}")
assert tm_elapsed > timeout * (1 - slop) and tm_elapsed < timeout * (1 + slop)
