#!/usr/bin/env python
"""Check init failing with atexit finishall.

---
plugin:
  - wandb
tag:
  skips:
    - platform: win
command:
  timeout: 30
env:
  - WANDB_INIT_TIMEOUT: "2"
  - WANDB_INIT_POLICY: fail
  - WANDB_BASE_URL: http://localhost:9999/bad/bad
  - WANDB_API_KEY: thisisnotavalidkey
assert:
  - :wandb:runs_len: 0
  - :yea:exit: 0
"""

import wandb

try:
    wandb.init()
except:  # noqa
    # We want to test that the atexit handler doesn't hang,
    # that's why we use a try/except here.
    # Skipping this test on Windows because there we
    # call os._exit(1) that can't be caught.
    pass
