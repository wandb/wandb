#!/usr/bin/env python
"""WB-7940: test that we can change env vars after wandb.login()"""

import os
from unittest import mock

import wandb
from wandb.util import mkdir_exists_ok

if __name__ == "__main__":
    wandb.login()
    test_dir = "test_dir"
    mkdir_exists_ok(test_dir)
    with mock.patch.dict(os.environ, {"WANDB_DIR": test_dir}):
        run = wandb.init(project="test-project")
        run.finish()

    assert os.path.exists(os.path.join(test_dir, "wandb", "debug.log"))
