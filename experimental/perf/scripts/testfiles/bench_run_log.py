from helper import generate_random_dict
import argparse
from datetime import datetime
import wandb

def measure_time(func):
    """Decorator to measure and return execution time of a function."""
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        result = func(*args, **kwargs)
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        print(f"{func.__name__}() time: {elapsed_time.total_seconds()}")
        return result, elapsed_time.total_seconds()
    return wrapper

@measure_time
def init_wandb(run_id, args):
    """Initialize a new W&B run."""
    wandb.init(
        project="perf-test",
        name=f"perf_{run_id}_{args.steps}steps_{args.metric_count}mc",
        config={
            "loop": {args.loop},
            "steps": {args.steps},
            "metric_count": {args.metric_count},
            "metric_key_size": {args.metric_key_size},
        }
    )

@measure_time
def log_metrics(steps, payload):
    """Log simulated accuracy and loss metrics to W&B."""
    for step in range(steps):
        wandb.log(payload)

@measure_time
def finish_wandb():
    """Mark W&B run as finished."""
    wandb.finish()

def run_experiment(args):
    """Run the training experiment, measuring initialization, logging, and finishing times."""
    print("##############################################################")
    print(f"# of training runs: {args.loop}")
    print(f"# of steps in each run: {args.steps}")
    print(f"# of metrics in each step: {args.metric_count}")
    print(f"metric key size: {args.metric_key_size}")
    start_time_str = datetime.now().strftime("%m%d%YT%H%M%S")
    print(f"Test start time: {start_time_str}")

    payload = generate_random_dict(args.metric_count, args.metric_key_size)
    total_start_time = datetime.now()

    for run in range(args.loop):
        run_id = f"{start_time_str}_{run}"
        print(f"\n--- Run {run + 1} ---")

        # Initialize W&B
        _, init_time = init_wandb(run_id, args)

        # Log the test metrics
        _, log_time = log_metrics(args.steps, payload)
        avg_log_time = round(log_time / args.steps, 5)
        print(f"log() count: {args.steps}")
        print(f"log() avg latency per call: {avg_log_time}")

        # Finish W&B run
        _, finish_time = finish_wandb()

        # Display experiment timing
        run_time = init_time + log_time + finish_time
        print(f"Total run time: {run_time}")

    total_end_time = datetime.now()
    total_time = total_end_time - total_start_time
    print(f"\nTotal training time: {total_time.total_seconds()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--loop", type=int, help="training run count", default=5)
    parser.add_argument("-s", "--steps", type=int, help="step count in each run", default=10)
    parser.add_argument("-n", "--metric_count", type=int, help="number of metrics to log", default=100)
    parser.add_argument("-m", "--metric_key_size", type=int, help="size of metric names in the log payload", default=10)

    args = parser.parse_args()
    run_experiment(args)
