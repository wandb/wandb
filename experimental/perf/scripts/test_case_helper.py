import os

from bench_run_log import run_experiment
from process_sar_helper import process_sar_files
from setup_helper import capture_sar_metrics


def bench_log(root_folder: str, loop_count: int, step: int):
    for loop in range(loop_count):
        log_folder = os.path.join(root_folder, f"loop{loop}_step{step}")
        os.makedirs(log_folder, exist_ok=True)
        capture_sar_metrics(log_folder)
        run_experiment(1, step, output_file=f"{log_folder}/results.json")
        process_sar_files(log_folder, "metrics.json")


def bench_log_scale_step(root_folder: str, list_of_steps: list[int]):
    loop = 1
    for step in list_of_steps:
        log_folder = os.path.join(root_folder, f"loop{loop}_step{step}")
        os.makedirs(log_folder, exist_ok=True)
        capture_sar_metrics(log_folder)
        run_experiment(loop, step, output_file=f"{log_folder}/results.json")
        process_sar_files(log_folder, "metrics.json")


def bench_log_scale_metric(root_folder: str, list_of_metric_count: list[int]):
    loop = 1
    step = 1000
    for mc in list_of_metric_count:
        log_folder = os.path.join(root_folder, f"loop{loop}_step{step}_metriccount{mc}")
        os.makedirs(log_folder, exist_ok=True)
        capture_sar_metrics(log_folder)
        run_experiment(loop, step, mc, output_file=f"{log_folder}/results.json")
        process_sar_files(log_folder, "metrics.json")
