#!/usr/bin/env python
"""Test stdin timeout

---
id: 0.0.6
"""
from wandb.errors import InputTimeoutError
from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.util import prompt_choices

c = prompt_choices(["1"], input_timeout=1)
print(c)
assert c == 0

timeout_log = "input timeout!"
try:
    stdin_timeout("waiting for input", 1, timeout_log)
except InputTimeoutError as e:
    assert str(e) == timeout_log

