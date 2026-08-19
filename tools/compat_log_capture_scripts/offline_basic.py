"""Default capture script for compat log fixtures.

This script is executed by tools/capture_compat_log.py inside a throwaway venv.
It expects:
  - CAPTURE_FIXTURE_NAME
  - CAPTURE_RESULT_PATH
"""

import json
import os
import platform
from pathlib import Path


fixture_name = os.environ["CAPTURE_FIXTURE_NAME"]
result_path = Path(os.environ["CAPTURE_RESULT_PATH"])

os.environ["WANDB_MODE"] = "offline"
os.environ["WANDB_ERROR_REPORTING"] = "false"
os.environ["WANDB_RUN_ID"] = fixture_name

import wandb

run = wandb.init(project="compat-corpus-captured")
for i in range(3):
    run.log({"x": i})
run.finish()

result_path.write_text(
    json.dumps(
        {
            "run_dir": run.settings.sync_dir,
            "wandb_version": wandb.__version__,
            "python_version": platform.python_version(),
        },
        indent=2,
    ),
    encoding="utf-8",
)
