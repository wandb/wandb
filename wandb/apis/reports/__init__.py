# flake8: noqa
import os

if os.getenv("WANDB_REPORT_API_ENABLE_V2"):
    from wandb.apis.reports.v2 import *
else:
    from wandb.apis.reports.v1 import *
