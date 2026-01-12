from __future__ import annotations

import argparse
import json
import logging
import os
import re

import wandb

logger = logging.getLogger(__name__)


def log_to_wandb(args: argparse.Namespace) -> None:
    # Initialize a W&B run
    with wandb.init(
        project=args.project, name=args.run_name, job_type="performance_test"
    ) as run:
        # Loop through each log file in the directory
        root_log_dir = args.folder
        dirs = os.listdir(root_log_dir)

        # Sort the directories based on the last numerical value found which is the sort_key
        sorted_dirs = sorted(dirs, key=lambda d: int(re.findall(r"\d+", d)[-1]))
        final_data = {}
        for dir in sorted_dirs:
            file_names = []
            # Either load the specific files from user inputs, or load *.json
            if args.list is not None:
                file_names = args.list.split(",")

            else:
                for file_name in os.listdir(os.path.join(root_log_dir, dir)):
                    if file_name.endswith(".json"):
                        file_names.append(file_name)

            for file_name in file_names:
                logger.info(f"logging data from {file_name} in {dir} ...")
                with open(os.path.join(root_log_dir, dir, file_name)) as f:
                    final_data.update(json.load(f))

            run.log(final_data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-f",
        "--folder",
        type=str,
        help="The root folder where the test results are stored",
        required=True,
    )
    parser.add_argument(
        "-n",
        "--run-name",
        type=str,
        help="The name of the run to log to W&B",
        required=True,
    )
    parser.add_argument(
        "-p",
        "--project",
        type=str,
        help="The W&B project to log to",
        required=True,
    )
    parser.add_argument(
        "-l",
        "--list",
        type=str,
        help="comma separated list of json files with data to send to W&B",
        required=False,
    )

    args = parser.parse_args()
    log_to_wandb(args)
