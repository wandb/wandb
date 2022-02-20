#!/usr/bin/env python
"""Enable tracelog to logger, make sure there are logs.

---
id: 0.debug.03-sentry-userproc
plugin:
  - wandb
tag:
  skips:
    - platform: win
      reason: wrong slashes in assert
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

from unittest import mock

import wandb


with mock.patch("wandb.sdk.wandb_init._WandbInit.init", mock.Mock(side_effect=Exception("injected"))):
    wandb.sdk.wandb_init._WandbInit.init.sentry_repr = None
    run = wandb.init()
