import argparse
import os
import re

import wandb


def parse_log(log_path):
    """Parses a performance test log file and extracts relevant metrics.

    Args:
        log_path (str): Path to the log file.

    Returns:
        dict: A dictionary of parsed metrics.
    """
    with open(log_path) as f:
        log_content = f.read()

    # Extract general information
    steps_per_run = int(
        re.search(r"# of steps in each run: (\d+)", log_content).group(1)
    )
    metrics_per_step = int(
        re.search(r"# of metrics in each step: (\d+)", log_content).group(1)
    )

    # Extract timing information for the run
    init_time = float(re.search(r"init_wandb\(\) time: ([\d.]+)", log_content).group(1))
    log_metrics_time = float(
        re.search(r"log_metrics\(\) time: ([\d.]+)", log_content).group(1)
    )
    finish_time = float(
        re.search(r"finish_wandb\(\) time: ([\d.]+)", log_content).group(1)
    )

    # Extract system metrics
    system_metrics = {}
    for match in re.finditer(r"\{([^}]+)\}", log_content):
        metrics = match.group(1).split(", ")
        for metric in metrics:
            key, value = metric.split(":")
            system_metrics[key] = float(value)

    # Consolidate all extracted data
    metrics = {
        "steps_per_run": steps_per_run,
        "metrics_per_step": metrics_per_step,
        "timing": {
            "init_time": init_time,
            "log_metrics_time": log_metrics_time,
            "finish_time": finish_time,
        },
        "system_metrics": system_metrics,
    }

    print(metrics)
    return metrics


def log_to_wandb(project_name, root_log_dir, run_name):
    """Logs the parsed performance test data to W&B.

    Args:
        project_name (str): Name of the W&B project.
        log_dir (str): Directory containing performance test logs.
    """
    wandb.init(project=project_name, name=run_name, job_type="performance_test")

    print("inside log_to_wandb")
    # Loop through each log file in the directory
    dirs = os.listdir(root_log_dir)
    # Sort directories based on the last numerical value found
    sorted_dirs = sorted(dirs, key=lambda d: int(re.findall(r"\d+", d)[-1]))
    for dir in sorted_dirs:
        log_path = os.path.join(root_log_dir, dir, "perftest.log")
        metrics = parse_log(log_path)

        # Log metrics to W&B
        wandb.log(
            {
                "steps_per_run": metrics["steps_per_run"],
                "metrics_per_step": metrics["metrics_per_step"],
                **metrics["timing"],  # Log timing data
                **metrics["system_metrics"],  # Log system metrics
            }
        )

    wandb.finish()


# Example usage
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
        "-n", "--run_name", type=str, help="Name of this test run", required=True
    )

    args = parser.parse_args()

    project_name = "perf_test_results"
    log_to_wandb(project_name, args.folder, args.run_name)
