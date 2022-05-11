import datetime
import os

import wandb


def main():
    project_base = os.environ.get(
        "PROJECT_BASE",
        "nightly"
    )
    time_stamp = os.environ.get(
        "TEST_RUN_TIME_STAMP",
        datetime.datetime.now().strftime("%Y%m%d"),
    )
    run = wandb.init(
        project=f"{project_base}-{time_stamp}",
        name=__file__,
    )
    run.log({"boom": 1})
    run.finish()


if __name__ == "__main__":
    main()
