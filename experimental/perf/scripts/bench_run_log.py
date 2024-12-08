import argparse
import json
from datetime import datetime

from setup_helper import generate_random_dict, get_logger

import wandb

logger = get_logger(__name__)


def measure_time(func):
    """Decorator to measure and return execution time of a function."""

    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        result = func(*args, **kwargs)
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        return result, round(elapsed_time.total_seconds(), 2)

    return wrapper


@measure_time
def init_wandb(
    run_id: str,
    loop_count: int,
    step_count: int,
    metric_count: int,
    metric_key_size: int,
):
    """Initialize a new W&B run."""
    wandb.init(
        project="perf-test",
        name=f"perf_run{run_id}_steps{step_count}_metriccount{metric_count}",
        config={
            "loop": {loop_count},
            "steps": {step_count},
            "metric_count": {metric_count},
            "metric_key_size": {metric_key_size},
        },
    )


@measure_time
def log_metrics(steps: int, payload: dict):
    """Log to W&B."""
    for _ in range(steps):
        wandb.log(payload)


@measure_time
def finish_wandb():
    """Mark W&B run as finished."""
    wandb.finish()


def run_experiment(
    loop_count=5,
    step_count=10,
    metric_count=100,
    metric_key_size=10,
    output_file="results.json",
):
    """Run the training experiment, measuring initialization, logging, and finishing times."""
    start_time_str = datetime.now().strftime("%m%d%YT%H%M%S")

    result_data = {}
    result_data["iteration_count"] = loop_count
    result_data["step_count"] = step_count
    result_data["metric_count"] = metric_count
    result_data["metric_key_size"] = metric_key_size

    logger.info("##############################################################")
    logger.info(f"# of training runs: {loop_count}")
    logger.info(f"# of steps in each run: {step_count}")
    logger.info(f"# of metrics in each step: {metric_count}")
    logger.info(f"metric key size: {metric_key_size}")
    logger.info(f"Test start time: {start_time_str}")

    payload = generate_random_dict(metric_count, metric_key_size)
    total_start_time = datetime.now()

    run_id = f"{start_time_str}"

    # Initialize W&B
    _, init_time = init_wandb(
        run_id, loop_count, step_count, metric_count, metric_key_size
    )
    result_data["init_time"] = init_time

    # Log the test metrics
    _, log_time = log_metrics(step_count, payload)
    result_data["log_time"] = log_time

    # compute the log() throughput rps (request per sec)
    log_rps = step_count // log_time
    result_data["log_rps"] = log_rps

    # Finish W&B run
    _, finish_time = finish_wandb()
    result_data["finish_time"] = finish_time

    # Display experiment timing
    run_time = init_time + log_time + finish_time
    result_data["sdk_run_time"] = run_time

    # write the result data to a json file
    with open(output_file, "w") as file:
        json.dump(result_data, file, indent=4)

    logger.info(json.dumps(result_data, indent=4))

    total_end_time = datetime.now()
    total_time = total_end_time - total_start_time
    logger.info(f"\nTotal test duration: {total_time.total_seconds()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l", "--loop", type=int, help="number of runs to perform.", default=5
    )
    parser.add_argument(
        "-s", "--steps", type=int, help="number of logging steps per run.", default=10
    )
    parser.add_argument(
        "-n",
        "--metric_count",
        type=int,
        help="number of metrics to each logging step.",
        default=100,
    )
    parser.add_argument(
        "-m",
        "--metric_key_size",
        type=int,
        help="length of metric names.",
        default=10,
    )

    parser.add_argument(
        "-o",
        "--outfile",
        type=str,
        help="performance test result output file.",
        default="results.json",
    )

    args = parser.parse_args()
    run_experiment(
        args.loop, args.steps, args.metric_count, args.metric_key_size, args.outfile
    )
