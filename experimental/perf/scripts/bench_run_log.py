import argparse
import json
import numpy as np
from datetime import datetime
from setup_helper import get_logger, get_payload
import wandb
import wandb.data_types

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
    step_count: int,
    metric_count: int,
    metric_key_size: int,
    data_type: str,
):
    """Initialize a new W&B run."""
    wandb.init(
        project="perf-test",
        name=f"perf_run{run_id}_steps{step_count}_metriccount{metric_count}",
        config={
            "steps": {step_count},
            "metric_count": {metric_count},
            "metric_key_size": {metric_key_size},
            "data_type": {data_type},
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
    step_count=10,
    metric_count=100,
    metric_key_size=10,
    output_file="results.json",
    data_type=None,
):
    """Run the training experiment while measuring initialization, logging, and finishing times."""
    result_data = {}
    result_data["step_count"] = step_count
    result_data["metric_count"] = metric_count
    result_data["metric_key_size"] = metric_key_size
    result_data["data_type"] = data_type

    run_start_time = datetime.now()
    start_time_str = run_start_time.strftime("%m%d%YT%H%M%S")
    logger.info(f"Test start time: {start_time_str}")
    run_id = f"{start_time_str}"

    # Initialize W&B
    _, init_time = init_wandb(
        run_id, step_count, metric_count, metric_key_size, data_type
    )
    result_data["init_time"] = init_time

    payload = get_payload(data_type, metric_count, metric_key_size)
    if not payload:
        logger.error(f"The payload is None for data type: {data_type}. Exiting.")
        return

    # Log the same payload in a tight loop
    _, log_time = log_metrics(step_count, payload)
    result_data["log_time"] = log_time

    # compute the log() throughput rps (request per sec)
    if log_time == 0:
        logger.warning("the measured time for log() is 0.")
        # Setting it to 0.1ms to avoid failing the math.
        log_time = 0.0001

    log_rps = round(step_count // log_time, 2)
    result_data["log_rps"] = log_rps

    # Finish W&B run
    _, finish_time = finish_wandb()
    result_data["finish_time"] = finish_time

    # Display experiment timing
    run_time = init_time + log_time + finish_time
    result_data["sdk_run_time"] = round(run_time, 2)

    # write the result data to a json file
    with open(output_file, "w") as file:
        json.dump(result_data, file, indent=4)

    logger.info(json.dumps(result_data, indent=4))

    test_run_time = datetime.now() - run_start_time
    logger.info(f"\nTotal run duration: {test_run_time.total_seconds()} seconds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l", "--loop", type=int, help="number of test iterations to perform.", default=1
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
    parser.add_argument(
        "-d",
        "--data_type",
        type=str,
        help="wandb data type to log. Default scalar.",
        default="scalar",
    )

    args = parser.parse_args()
    for _ in range(args.loop):
        run_experiment(
            args.steps, args.metric_count, args.metric_key_size, args.outfile, args.data_type
        )
