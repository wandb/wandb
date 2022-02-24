#!/usr/bin/env python
"""Enable tracelog to logger, make sure there are logs.

---
id: 0.debug.04-sentry-tags
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:sentry_events[0][level]: error
  - :wandb:sentry_events[0][exception][values][0][type]: FileNotFoundError
  - :wandb:sentry_events[0][tags][entity]: mock_server_entity
  - :wandb:sentry_events[0][tags][deployment]: local
  - :wandb:sentry_events[0][tags][_require_service]: True
  - :wandb:sentry_events[0][tags][process_context]: internal
  - :wandb:sentry_events[0][tags][python_runtime]: python
  - :yea:exit: 0
"""
import shutil

import wandb

wandb.require("service")

# Triggers a FileNotFoundError from the internal process
# because the internal process reads/writes to the current run directory.
run = wandb.init()
shutil.rmtree(run.dir)
run.log({"data": 5})
