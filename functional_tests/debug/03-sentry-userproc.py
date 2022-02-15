#!/usr/bin/env python
"""Enable tracelog to logger, make sure there are logs.

---
id: 0.debug.03-sentry-userproc
plugin:
  - wandb
assert:
  - :wandb:runs_len: 0
  - :wandb:sentry_events[0][level]: error
  - :wandb:sentry_events[0][platform]: python
  - :wandb:sentry_events[0][exception][values][0][type]: Exception
  - :wandb:sentry_events[0][exception][values][0][value]: injected
  - :wandb:sentry_events[0][exception][values][0][stacktrace][frames][0][filename]: wandb/sdk/wandb_init.py
  - :wandb:sentry_events[0][exception][values][0][stacktrace][frames][0][function]: init
  - :yea:exit: 1
"""

import time
from unittest import mock

import wandb

try:
    with mock.patch("wandb.sdk.wandb_init._WandbInit.init", side_effect=Exception("injected")) as m:
        run = wandb.init()
finally:
    time.sleep(3)
