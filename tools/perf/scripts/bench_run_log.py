import argparse
import json
import multiprocessing as mp
import random
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import wandb

from .setup_helper import get_logger

logger = get_logger(__name__)


class Timer:
    """A simple timer class to measure execution time."""

    def __init__(self):
        self.start_time = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    def start(self):
        self.start_time = datetime.now()

    def stop(self):
        return (datetime.now() - self.start_time).total_seconds()


class PayloadGenerator:
    """Generates a payload for logging in the performance testing.

    Args:
        data_type: The type of data to log.
        metric_count: The number of metrics.
        metric_key_size: The size (in characters) of the metric.
    """

    def __init__(
        self,
        data_type: Literal["scalar", "audio", "video", "image", "table"],
        metric_count: int,
        metric_key_size: int,
    ):
        self.data_type = data_type
        self.metric_count = metric_count
        self.metric_key_size = metric_key_size

    def random_string(self, size: int) -> str:
        """Generates a random string of a given size.

        Args:
            size: The size of the string.

        Returns:
            str: A random string of the given size.
        """
        return "".join(
            random.choices(string.ascii_letters + string.digits + "_", k=size)
        )

    def generate(self) -> dict:
        """Generates a payload for logging.

        Returns:
            dict: A dictionary with the payload.

        Raises:
            ValueError: If the data type is invalid.
        """
        if self.data_type == "audio":
            return self.generate_audio()
        elif self.data_type == "scalar":
            return self.generate_scalar()
        elif self.data_type == "table":
            return self.generate_table()
        elif self.data_type == "image":
            return self.generate_image()
        elif self.data_type == "video":
            return self.generate_video()

        else:
            raise ValueError(f"Invalid data type: {self.data_type}")

    def generate_audio(self) -> dict[str, wandb.Audio]:
        """Generates a payload for logging audio data.

        Returns:
            dict: A dictionary with the audio data.
        """
        duration = 5  # make a 5s long audio
        sample_rate = 44100
        frequency = 440

        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        audio_data = np.sin(2 * np.pi * frequency * t)
        audio_obj = wandb.Audio(audio_data, sample_rate=sample_rate)
        return {
            self.random_string(self.metric_key_size): audio_obj
            for _ in range(self.metric_count)
        }

    def generate_scalar(self) -> dict[str, int]:
        """Generates a payload for logging scalar data.

        Returns:
            dict: A dictionary with the scalar data.
        """
        return {
            self.random_string(self.metric_key_size): random.randint(1, 10**6)
            for _ in range(self.metric_count)
        }

    def generate_table(self) -> dict[str, wandb.Table]:
        """Generates a payload for logging 1 table.

        For the table, it uses
            self.metric_count as the number of columns
            self.metric_key_size as the number of rows.

        Returns:
            dict: A dictionary with the table data.
        """
        num_of_columns = self.metric_count
        num_of_rows = self.metric_key_size

        columns = [f"Field_{i+1}" for i in range(num_of_columns)]
        data = [
            [self.random_string(self.metric_key_size) for _ in range(num_of_columns)]
            for _ in range(num_of_rows)
        ]
        table = wandb.Table(columns=columns, data=data)
        return {"perf_test_table": table}

    def generate_image(self) -> dict[str, wandb.Image]:
        """Generates a payload for logging images.

        Returns:
            dict: A dictionary with image data.
        """
        # Create a random RGB image (100x100 pixels)
        # Each pixel value is an integer between 0 and 255 for RGB channels
        random_image = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        image_obj = wandb.Image(random_image, caption="Random image")

        return {
            self.random_string(self.metric_key_size): image_obj
            for _ in range(self.metric_count)
        }

    def generate_video(self) -> dict[str, wandb.Video]:
        """Generates a payload for logging videos.

        Returns:
            dict: A dictionary with video data.
        """
        # Create a random video (50 frames, 64x64 pixels, 3 channels for RGB)
        frames = np.random.randint(0, 256, (50, 64, 64, 3), dtype=np.uint8)
        video_obj = wandb.Video(frames, fps=10, caption="Randomly generated video")

        return {
            self.random_string(self.metric_key_size): video_obj
            for _ in range(self.metric_count)
        }


class Experiment:
    """A class to run the performance test.

    Args:
        num_steps: The number of logging steps per run.
        num_metrics: The number of metrics to log per step.
        metric_key_size: The length of metric names.
        output_file: The output file to store the performance test results.
        data_type: The wandb data type to log.
        is_unique_payload: Whether to use a new set of metrics or reuse the same set for each step.
        time_delay_second: Sleep time between step.

    When to set "is_unique_payload" to True?

    Performance benchmarks are usually done on basic use case to form the baseline, then building on top
    of the baseline, we scales up the various dimensions (# of steps, # of metrics, metric size, etc) to
    characterize scalability.

    For benchmarking or regression detection, set is_unique_payload to False (default). For stress
    testing or simulating huge workload w/ million+ metrics, set is_unique_payload to True.
    """

    def __init__(
        self,
        num_steps: int = 10,
        num_metrics: int = 100,
        metric_key_size: int = 10,
        output_file: str = "results.json",
        data_type: Literal["scalar", "audio", "video", "image", "table"] = "scalar",
        is_unique_payload: bool = False,
        time_delay_second: float = 0.0,
    ):
        self.num_steps = num_steps
        self.num_metrics = num_metrics
        self.metric_key_size = metric_key_size
        self.output_file = output_file
        self.data_type = data_type
        self.is_unique_payload = is_unique_payload
        self.time_delay_second = time_delay_second

    def run(self, repeat: int = 1):
        for _ in range(repeat):
            self.single_run()

    def single_run(self):
        """Run a simple experiment to log metrics to W&B.

        Measuring the time for init(), log(), and finish() operations.
        """
        start_time = datetime.now()
        start_time_str = start_time.strftime("%m%d%YT%H%M%S")
        logger.info(f"Test start time: {start_time_str}")

        result_data = {
            "num_steps": self.num_steps,
            "num_metrics": self.num_metrics,
            "metric_key_size": self.metric_key_size,
            "data_type": self.data_type,
        }

        # Initialize W&B
        with Timer() as timer:
            run = wandb.init(
                project="perf-test",
                name=f"perf_run={start_time_str}_steps={self.num_steps}_metrics={self.num_metrics}",
                config=result_data,
            )
            result_data["init_time"] = timer.stop()

        # pre-generate all the payloads
        try:
            if self.is_unique_payload:
                num_of_unique_payload = self.num_steps
            else:
                num_of_unique_payload = 1

            payloads = [
                PayloadGenerator(
                    self.data_type, self.num_metrics, self.metric_key_size
                ).generate()
                for _ in range(num_of_unique_payload)
            ]
        except ValueError as e:
            logger.error(f"Failed to generate payload: {e}")
            return

        # Log the payload $step_count times
        with Timer() as timer:
            for s in range(self.num_steps):
                if self.is_unique_payload:
                    run.log(payloads[s])
                else:
                    run.log(payloads[0])

                # 12/20/2024 - Wai
                # HACKAROUND: We ran into issues logging too many unique metrics
                # returning 500s/502s.  Adding a small sleep between step
                # works around it for now.

                # Optional sleep time, use it to reproduce real-life
                # workload where logging steps aren't in a tight loop
                # Just remember the result_data["log_time"] will include
                # your sleep time for all the steps.
                if self.time_delay_second > 0:
                    time.sleep(self.time_delay_second)

            result_data["log_time"] = timer.stop()

        # compute the log() throughput rps (request per sec)
        if result_data["log_time"] == 0:
            logger.warning("the measured time for log() is 0.")
            # Setting it to 0.1ms to avoid failing the math.
            result_data["log_time"] = 0.0001

        result_data["log_rps"] = round(self.num_steps / result_data["log_time"], 2)

        # Finish W&B run
        with Timer() as timer:
            run.finish()
            result_data["finish_time"] = timer.stop()

        # Display experiment timing
        run_time = (
            result_data["init_time"]
            + result_data["log_time"]
            + result_data["finish_time"]
        )
        result_data["sdk_run_time"] = round(run_time, 2)

        # write the result data to a json file
        with open(self.output_file, "w") as file:
            json.dump(result_data, file, indent=4)

        logger.info(json.dumps(result_data, indent=4))
        total_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"\nTotal run duration: {total_time:.2f} seconds")


def run_parallel_experiment(
    *,
    num_processes: int,
    num_steps: int,
    num_metrics: int,
    data_type: Literal["scalar", "audio", "video", "image", "table"],
    metric_key_size: int,
    log_folder: Path,
):
    """A helper function to start multiple wandb runs in parallel.

    Args:
        num_of_processes: Number of parallel wandb runs to start.
        num_steps: Number of steps within the loop.
        num_metrics: Number of metrics to log per step.
        data_type: Wandb data type for the test payload
        metric_key_size: The length of metric names.
        log_folder: The root directory where results will be stored.
    """
    wandb.setup()
    processes = []
    for i in range(num_processes):
        p = mp.Process(
            target=Experiment(
                num_steps=num_steps,
                num_metrics=num_metrics,
                metric_key_size=metric_key_size,
                output_file=log_folder / f"results.{i+1}.json",
                data_type=data_type,
            ).run,
            kwargs=dict(
                repeat=1,
            ),
        )
        p.start()
        logger.info(f"The {i}-th process (pid: {p.pid}) has started.")
        processes.append(p)

    # now wait for all processes to finish and exit
    for p in processes:
        p.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-r",
        "--repeat",
        type=int,
        default=1,
        help="The number of times to repeat the experiment.",
    )
    parser.add_argument(
        "-s",
        "--steps",
        type=int,
        default=10,
        help="The number of logging steps per run.",
    )
    parser.add_argument(
        "-n",
        "--num-metrics",
        type=int,
        default=100,
        help="The number of metrics to log per step.",
    )
    parser.add_argument(
        "-m",
        "--metric-key-size",
        type=int,
        default=10,
        help="The length of metric names.",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        type=str,
        default="results.json",
        help="The output file to store the performance test results.",
    )
    parser.add_argument(
        "-d",
        "--data-type",
        type=str,
        choices=["scalar", "audio", "video", "image", "table"],
        default="scalar",
        help="The wandb data type to log. Defaults to scalar.",
    )
    parser.add_argument(
        "-u",
        "--unique-payload",
        type=bool,
        default=False,
        help="False - reuse the same payload in each log(), new payload if True.",
    )
    parser.add_argument(
        "-t",
        "--time-delay-second",
        type=float,
        default=0,
        help="e.g. -t 1.0  Sleep time in seconds between each step.",
    )

    args = parser.parse_args()

    Experiment(
        num_steps=args.steps,
        num_metrics=args.num_metrics,
        metric_key_size=args.metric_key_size,
        output_file=args.outfile,
        data_type=args.data_type,
        is_unique_payload=args.unique_payload,
        time_delay_second=args.time_delay_second,
    ).run(args.repeat)
