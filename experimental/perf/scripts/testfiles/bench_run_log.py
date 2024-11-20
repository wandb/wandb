import argparse
import json
import wandb
from datetime import datetime
from helper import generate_random_dict


def measure_time(func):
    """Decorator to measure and return execution time of a function."""

    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        result = func(*args, **kwargs)
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        # print(f"{func.__name__}() time: {elapsed_time.total_seconds()}")
        return result, round(elapsed_time.total_seconds(), 2)

    return wrapper


@measure_time
def init_wandb(run_id: str, args: argparse):
    """Initialize a new W&B run."""
    wandb.init(
        project="perf-test",
        name=f"perf_run{run_id}_steps{args.steps}_metriccount{args.metric_count}",
        config={
            "loop": {args.loop},
            "steps": {args.steps},
            "metric_count": {args.metric_count},
            "metric_key_size": {args.metric_key_size},
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


def run_experiment(args: argparse):
    """Run the training experiment, measuring initialization, logging, and finishing times."""
    start_time_str = datetime.now().strftime("%m%d%YT%H%M%S")

    result_data = {}
    result_data["iteration_count"] = int(args.loop)
    result_data["step_count"] = int(args.steps)
    result_data["metric_count"] = int(args.metric_count)
    result_data["metric_key_size"] = int(args.metric_key_size)

    print("##############################################################")
    print(f"# of training runs: {args.loop}")
    print(f"# of steps in each run: {args.steps}")
    print(f"# of metrics in each step: {args.metric_count}")
    print(f"metric key size: {args.metric_key_size}")
    print(f"Test start time: {start_time_str}")

    payload = generate_random_dict(args.metric_count, args.metric_key_size)
    total_start_time = datetime.now()

    for run in range(args.loop):
        run_id = f"{start_time_str}_{run}"
        print(f"\n--- Run {run + 1} ---")

        # Initialize W&B
        _, init_time = init_wandb(run_id, args)
        result_data["init_time"] = init_time

        # Log the test metrics
        _, log_time = log_metrics(args.steps, payload)
        result_data["log_time"] = log_time

        # Finish W&B run
        _, finish_time = finish_wandb()
        result_data["finish_time"] = finish_time

        # Display experiment timing
        run_time = init_time + log_time + finish_time
        result_data["sdk_run_time"] = run_time

        # write the result data to a json file
        with open(args.outfile, "w") as file:
            json.dump(result_data, file, indent=4)

        print(json.dumps(result_data, indent=4))

    total_end_time = datetime.now()
    total_time = total_end_time - total_start_time
    print(f"\nTotal test duration: {total_time.total_seconds()}")


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
    run_experiment(args)
