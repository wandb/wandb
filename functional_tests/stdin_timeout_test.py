#!/usr/bin/env python
"""Test stdin timeout

---
id: 0.0.6
plugin:
  - wandb
"""
from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.errors import InputTimeoutError


timeout_log = "input timeout!"
try:
    stdin_timeout("waiting for input", 1, timeout_log)
except InputTimeoutError as e:
    assert e.message == timeout_log
