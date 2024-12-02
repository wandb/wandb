import os

from bench_run_log import run_experiment
from process_sar_helper import process_sar_files
from setup_helper import capture_sar_metrics


def bench_log(root_folder: str, loop_count: int, step: int):
    """Runs a set of load tests with the same parameter.

    The goal is to measure the performance of a baseline test with reliable
    and repeatable averages and max computed.
    """
    mc = 100
    step = 2000
    sort_key = 1

    for loop in range(1, loop_count + 1):
        run_experiment_helper(loop, step, mc, root_folder, sort_key)
        sort_key += 1


def bench_log_scale_step(root_folder: str, list_of_steps: list[int]):
    """Runs a set of load tests with increasing # of steps.

    The goal is to measure the performance impact of runs with more steps.
    """
    loop = 1
    mc = 100
    sort_key = 1

    for step in list_of_steps:
        run_experiment_helper(loop, step, mc, root_folder, sort_key)
        sort_key += 1


def bench_log_scale_metric(root_folder: str, list_of_metric_count: list[int]):
    """Runs a set of load tests with increasing # of metrics per step.

    The goal is to measure the performance impact of more metrics logged per step.
    """
    loop = 1
    step = 1000
    sort_key = 1
    for mc in list_of_metric_count:
        run_experiment_helper(loop, step, mc, root_folder, sort_key)
        sort_key += 1


def run_experiment_helper(
    loop, step, mc, root_folder, sort_key, output_file="results.json"
):
    """A helper to do the standard perf test setup.

    1) create a folder for this particular load test iteration
    2) start capturing resource metrics
    3) run the actual load tests
    4) end the resource metrics and compute the summary stats
    """
    log_folder = os.path.join(
        root_folder, f"loop{loop}_step{step}_metriccount{mc}_{sort_key}"
    )

    os.makedirs(log_folder, exist_ok=True)

    capture_sar_metrics(log_folder)

    run_experiment(loop, step, mc, output_file=f"{log_folder}/{output_file}")

    process_sar_files(log_folder)
