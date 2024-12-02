import argparse
import json
import os
import re

import wandb


def log_to_wandb(args: argparse) -> None:
    # Initialize a W&B run
    run = wandb.init(project=args.project, name=args.run, job_type="performance_test")

    # Loop through each log file in the directory
    root_log_dir = args.folder
    dirs = os.listdir(root_log_dir)

    # Sort the directories based on the last numerical value found
    sorted_dirs = sorted(dirs, key=lambda d: int(re.findall(r"\d+", d)[-1]))
    final_data = {}
    for dir in sorted_dirs:
        # Load the list of json files and combine them into one dictionary to send
        for f in args.list.split(","):
            with open(os.path.join(root_log_dir, dir, f)) as f:
                json_data = json.load(f)
                final_data.update(json_data)

        run.log(final_data)

    run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-f",
        "--folder",
        type=str,
        help="Test result ROOT folder (required)",
        required=True,
    )
    parser.add_argument(
        "-n", "--run", type=str, help="Name of this test run", required=True
    )
    parser.add_argument(
        "-p", "--project", type=str, help="W&B project name", required=True
    )
    parser.add_argument(
        "-l",
        "--list",
        type=str,
        help="comma separated list of json files with data to send to W&B",
        required=False,
        default="results.json,metrics.json",
    )

    args = parser.parse_args()
    log_to_wandb(args)
