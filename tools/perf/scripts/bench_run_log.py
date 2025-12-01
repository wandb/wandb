from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import random
import string
import time
from datetime import datetime
from typing import Literal

import numpy as np
import wandb

from .setup_helper import setup_package_logger

logger = logging.getLogger(__name__)


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
        return round((datetime.now() - self.start_time).total_seconds(), 2)


class PayloadGenerator:
    """Generates a payload for logging in the performance testing.

    Args:
        data_type: The type of data to log.
        sparse_metric_count: Number of sparse metrics to log.
        metric_key_size: The size (in characters) of the metric.
        num_steps: Number of steps in the test.
        fraction: The fraction (%) of the base payload to log per step.
        is_unique_payload: If true, every step logs a unique payload
        dense_metric_count: Number of dense metrics (logged every step)
        sparse_stride_size: Number of steps to skip before logging the sparse metrics
    """

    def __init__(
        self,
        *,
        data_type: Literal[
            "scalar", "audio", "video", "image", "table", "prefixed_scalar"
        ],
        sparse_metric_count: int,
        metric_key_size: int,
        num_steps: int,
        fraction: float,
        is_unique_payload: bool,
        dense_metric_count: int,
        sparse_stride_size: int,
    ):
        self.data_type = data_type
        self.sparse_metric_count = sparse_metric_count
        self.metric_key_size = metric_key_size
        self.num_steps = num_steps
        self.fraction = fraction
        self.is_unique_payload = is_unique_payload
        self.dense_metric_count = dense_metric_count
        self.sparse_stride_size = sparse_stride_size
        self.sparse_metrics = None

        self.metrics_count_per_step = int(self.sparse_metric_count * self.fraction)
        if self.is_unique_payload:
            # every step use a unique payload
            self.num_of_unique_payload = self.num_steps

        elif self.fraction < 1.0:
            # every step logs a subset of a base payload
            self.num_of_unique_payload = int(
                self.sparse_metric_count // self.metrics_count_per_step
            )

        else:
            # every step logs the same set of base payload
            self.num_of_unique_payload = 1

        logger.info(f"dense_metric_count: {self.dense_metric_count}")
        logger.info(
            f"metrics_count_per_step: {self.metrics_count_per_step + self.dense_metric_count}"
        )
        logger.info(f"num_of_unique_payload: {self.num_of_unique_payload}")

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

    def generate(self) -> list[dict]:
        """Generates a list of payload for logging.

        Returns:
            List: A list of dictionary with payloads.

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
        elif self.data_type == "prefixed_scalar":
            return self.generate_prefixed_scalar()

        else:
            raise ValueError(f"Invalid data type: {self.data_type}")

    def generate_audio(self) -> list[dict[str, wandb.Audio]]:
        """Generates a payload for logging audio data.

        Returns:
            List: A list of dictionary with the audio data.
        """
        payloads = []
        for _ in range(self.num_of_unique_payload):
            duration = 5  # make a 5s long audio
            sample_rate = 44100
            frequency = 440

            t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
            audio_data = np.sin(2 * np.pi * frequency * t)
            audio_obj = wandb.Audio(audio_data, sample_rate=sample_rate)
            payloads.append(
                {
                    self.random_string(self.metric_key_size): audio_obj
                    for _ in range(self.sparse_metric_count)
                }
            )

        return payloads

    def generate_scalar(self) -> list[dict[str, int]]:
        """Generates the payloads for logging scalar data.

        Returns:
            List: A list of dictionaries with the scalar data.
        """
        # Generate dense metrics if applicable
        dense_metrics = {
            self.random_string(self.metric_key_size): random.randint(1, 10**2)
            for _ in range(self.dense_metric_count)
        }

        # Log example dense metric if available
        if dense_metrics:
            example_key = next(iter(dense_metrics))
            logger.info(f"Example dense metric: {example_key}")

        if self.sparse_stride_size > 0:
            # Generate a single payload for sparse logging every X steps
            self.sparse_metrics = {
                f"sparse/acc{i}": random.randint(1, 10**2)
                for i in range(self.sparse_metric_count)
            }

            payloads = [{**dense_metrics}]

        else:
            # Generate payloads with sparse metrics + optional dense metrics prepended
            payloads = [
                {
                    **dense_metrics,
                    **{
                        self.random_string(self.metric_key_size): random.randint(
                            1, 10**2
                        )
                        for _ in range(self.metrics_count_per_step)
                    },
                }
                for _ in range(self.num_of_unique_payload)
            ]

        return payloads

    def generate_prefixed_scalar(self) -> list[dict[str, int]]:
        """Generates the payloads for logging scalar data with prefixes.

           This makes all the runs in the same project to have the repeating metric names.

        Returns:
            List: A list of dictionaries with the scalar data.
        """
        # Generate dense metrics if applicable
        dense_metrics = {
            f"dense/accuracy{i}": random.randint(1, 10**2)
            for i in range(self.dense_metric_count)
        }

        # Log example dense metric if available
        if dense_metrics:
            example_key = next(iter(dense_metrics))
            logger.info(f"Example dense metric: {example_key}")

        if self.sparse_stride_size > 0:
            # Generate a single payload for sparse logging every X steps
            self.sparse_metrics = {
                f"sparse/acc{i}": random.randint(1, 10**2)
                for i in range(self.sparse_metric_count)
            }

            payloads = [{**dense_metrics}]

        else:
            # Generate payloads with sparse metrics + optional dense metrics prepended
            payloads = [
                {
                    **dense_metrics,
                    **{
                        f"eval{x}/loss{i}": random.randint(1, 10**2)
                        for i in range(self.metrics_count_per_step // 2)
                    },
                    **{
                        f"rank{x}/accuracy{i}": random.randint(1, 10**2)
                        for i in range(self.metrics_count_per_step // 2)
                    },
                }
                for x in range(self.num_of_unique_payload)
            ]

        return payloads

    def generate_table(self) -> list[dict[str, wandb.Table]]:
        """Generates a payload for logging 1 table.

        For the table, it uses
            self.sparse_metric_count as the number of columns
            self.metric_key_size as the number of rows.

        Returns:
            List: A dictionary with the table data.
        """
        payloads = []
        for p in range(self.num_of_unique_payload):
            num_of_columns = self.sparse_metric_count
            num_of_rows = self.metric_key_size

            columns = [f"Field_{i + 1}" for i in range(num_of_columns)]
            data = [
                [
                    self.random_string(self.metric_key_size)
                    for _ in range(num_of_columns)
                ]
                for _ in range(num_of_rows)
            ]
            table = wandb.Table(columns=columns, data=data)
            payloads.append({f"table_{p}": table})

        return payloads

    def generate_image(self) -> list[dict[str, wandb.Image]]:
        """Generates a payload for logging images.

        Returns:
            List: A list of dictionary with image data.
        """
        payloads = []
        for _ in range(self.num_of_unique_payload):
            # Create a random RGB image (100x100 pixels)
            # Each pixel value is an integer between 0 and 255 for RGB channels
            random_image = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            image_obj = wandb.Image(random_image, caption="Random image")

            payloads.append(
                {
                    self.random_string(self.metric_key_size): image_obj
                    for _ in range(self.sparse_metric_count)
                }
            )

        return payloads

    def generate_video(self) -> list[dict[str, wandb.Video]]:
        """Generates a payload for logging videos.

        This function creates HD videos that are 1280 x 720 with 16 frames per second as payload
        for logging.  It used self.metric_key_size as the video length in second.

        Returns:
            List: A list of dictionary with video data.
        """
        payloads = []
        # Video properties for HD video
        frame_width = 1280
        frame_height = 720
        fps = 16
        video_len_in_sec = self.metric_key_size
        video_prefixes = ["video_acc", "video_prob", "video_loss", "video_labels"]
        for i in range(self.num_of_unique_payload):
            frames = np.random.randint(
                0,
                256,
                (video_len_in_sec * fps, frame_height, frame_width, 3),
                dtype=np.uint8,
            )
            video_obj = wandb.Video(
                frames, fps=fps, caption=f"Randomly generated video {i}"
            )

            payloads.append(
                {
                    f"{video_prefixes[s % 4]}/{i}_{s}": video_obj
                    for s in range(self.sparse_metric_count)
                }
            )

        return payloads


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
        run_id: ID of the existing run to resume from.
        resume_mode: The mode of resuming. Used when run_id is passed in.
        fraction: The % (in fraction) of metrics to log in each step.
        dense_metric_count: Number of dense metrics to be logged every step.
                            The dense metrics is a separate set of metrics from the sparse metrics.
        fork_from: The fork from string (formatted) e.g. f"{original_run.id}?_step=200"
        project: The W&B project name to log to
        sparse_stride_size: The number of steps to skip before logging the sparse metrics
        starting_global_step: The starting global step for this run
        mode: The mode to run the experiment. Defaults to "online".

    When to set "is_unique_payload" to True?

    Performance benchmarks are usually done on the basic use case to form the baseline, then on top
    of it, scale tests of various dimensions are run (# of steps, # of metrics, metric size, etc) to
    characterize its scalability.

    For benchmarks or regression detection testings, set is_unique_payload to False (default). For stress
    testings or simulating huge workload w/ million+ metrics, set is_unique_payload to True.
    """

    def __init__(
        self,
        *,
        num_steps: int = 10,
        num_metrics: int = 100,
        metric_key_size: int = 10,
        output_file: str = "results.json",
        data_type: Literal[
            "scalar", "audio", "video", "image", "table", "prefixed_scalar"
        ] = "scalar",
        is_unique_payload: bool = False,
        time_delay_second: float = 0.0,
        run_id: str | None = None,
        resume_mode: str | None = None,
        fraction: float = 1.0,
        dense_metric_count: int = 0,
        fork_from: str | None = None,
        project: str = "perf-test",
        sparse_stride_size: int = 0,
        starting_global_step: int = 0,
        mode: Literal["shared", "online"] = "online",
    ):
        self.num_steps = num_steps
        self.num_metrics = num_metrics
        self.metric_key_size = metric_key_size
        self.output_file = output_file
        self.data_type = data_type
        self.is_unique_payload = is_unique_payload
        self.time_delay_second = time_delay_second
        self.run_id = run_id
        self.resume_mode = resume_mode
        self.fraction = fraction
        self.dense_metric_count = dense_metric_count
        self.fork_from = fork_from
        self.project = project
        self.sparse_stride_size = sparse_stride_size
        self.starting_global_step = starting_global_step
        self.mode = mode

    def run(self, repeat: int = 1):
        for _ in range(repeat):
            self.single_run()

    def parallel_runs(self, num_of_parallel_runs: int = 1):
        """Runs multiple instances of single_run() in parallel processes.

        Args:
            num_of_parallel_runs (int): Number of parallel runs to execute.
        """
        wandb.setup()
        processes = []
        for i in range(num_of_parallel_runs):
            p = mp.Process(target=self.run)
            p.start()
            logger.info(f"The {i}-th process (pid: {p.pid}) has started.")
            processes.append(p)

        for p in processes:
            p.join()

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
            name = (
                f"perf_run={start_time_str}_steps={self.num_steps}_metrics={self.num_metrics}"
                if self.run_id is None
                else None
            )
            init_timeout = 600 if self.fork_from else 90

            run = wandb.init(
                project=self.project,
                name=name,
                id=self.run_id,
                mode=self.mode,
                resume=self.resume_mode,
                fork_from=self.fork_from,
                config=result_data if self.run_id is None else None,
                settings=wandb.Settings(
                    init_timeout=init_timeout,
                ),
            )

            if self.run_id is None:
                logger.info(f"New run {run.id} initialized.")
            elif self.resume_mode:
                logger.info(f"Resuming run {self.run_id} with {self.resume_mode}.")
            if self.mode == "shared":
                logger.info(f"Shared mode enabled, logging to run {self.run_id}.")

            result_data["init_time"] = timer.stop()

        # pre-generate all the payloads
        logger.info("Generating test payloads ...")
        generator = PayloadGenerator(
            data_type=self.data_type,
            sparse_metric_count=self.num_metrics,
            metric_key_size=self.metric_key_size,
            num_steps=self.num_steps,
            fraction=self.fraction,
            is_unique_payload=self.is_unique_payload,
            dense_metric_count=self.dense_metric_count,
            sparse_stride_size=self.sparse_stride_size,
        )
        payloads = generator.generate()

        logger.info(f"Start logging {self.num_steps} steps ...")
        with Timer() as timer:
            for s in range(self.num_steps):
                global_values = {}
                global_values["global_step"] = self.starting_global_step + s

                if self.is_unique_payload or self.fraction < 1.0:
                    run.log({**global_values, **(payloads[s % len(payloads)])})
                else:
                    if self.sparse_stride_size > 0 and s % self.sparse_stride_size == 0:
                        # log the sparse + dense metrics
                        run.log(
                            {
                                **global_values,
                                **(generator.sparse_metrics),
                                **(payloads[0]),
                            }
                        )
                    else:
                        # log only the dense metric
                        run.log({**global_values, **(payloads[0])})

                if self.time_delay_second > 0:
                    time.sleep(self.time_delay_second)

            result_data["log_time"] = timer.stop()
            result_data["run_id"] = run.id

        # compute the log() throughput rps (request per sec)
        if result_data["log_time"] == 0:
            logger.warning("the measured time for log() is 0.")
            # Setting it to 0.1ms to avoid failing the math.
            result_data["log_time"] = 0.01

        # adjust for the sleep time injected
        if self.time_delay_second > 0:
            result_data["log_time"] -= self.time_delay_second * self.num_steps

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


if __name__ == "__main__":
    setup_package_logger()
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
        help="The number of sparse metrics to log per step (optional: "
        "use together with -f to control %).",
    )
    parser.add_argument(
        "-m",
        "--metric-key-size",
        type=int,
        default=10,
        help='The length of metric names. If the --data-type is "video", '
        "then this represents the video length in second.",
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
        choices=["scalar", "audio", "video", "image", "table", "prefixed_scalar"],
        default="scalar",
        help="The wandb data type to log. Defaults to scalar.",
    )
    parser.add_argument(
        "-u",
        "--unique-payload",
        type=bool,
        default=False,
        help="If false, it logs the same payload at each step. "
        "If true, each step has different payload.",
    )
    parser.add_argument(
        "-t",
        "--time-delay-second",
        type=float,
        default=0,
        help="The sleep time between step in seconds e.g. -t 1.0",
    )

    parser.add_argument(
        "-i",
        "--run-id",
        type=str,
        help="The run id. e.g. -i 123abc to resume this run id.",
    )

    parser.add_argument(
        "-j",
        "--resume-mode",
        type=str,
        choices=["must", "allow", "never"],
        default=None,
        help="Use with --run-id. The resume mode.",
    )

    parser.add_argument(
        "-g",
        "--global-step",
        type=int,
        default=0,
        help="Set the global_step",
    )

    parser.add_argument(
        "-f",
        "--fraction",
        type=float,
        default=1.0,
        help="The fraction (i.e. percentage) of sparse metrics to log in each step.",
    )

    parser.add_argument(
        "-c",
        "--dense_metric_count",
        type=int,
        default=0,
        help="The number of dense metrics that are logged at every step. "
        "This is a separate set from the sparse metrics.",
    )

    parser.add_argument(
        "-x",
        "--fork-run-id",
        type=str,
        help="The source run's id to fork from.",
    )

    parser.add_argument(
        "-y",
        "--fork-step",
        type=str,
        default="1",
        help="The step to fork from.",
    )

    parser.add_argument(
        "-p",
        "--project",
        type=str,
        default="perf-test",
        help="The W&B project to log to.",
    )

    parser.add_argument(
        "-z",
        "--parallel",
        type=int,
        default=1,
        help="The number of wandb instances to launch",
    )

    parser.add_argument(
        "-w",
        "--sparse-stride-size",
        type=int,
        default=0,
        help="The number of steps to skip for logging the sparse payload",
    )

    parser.add_argument(
        "-a",
        "--mode",
        type=str,
        choices=["shared", "online"],
        default="online",
        help="The mode to run the experiment.",
    )

    args = parser.parse_args()

    fork_from: str | None = None
    if args.fork_run_id:
        fork_from = f"{args.fork_run_id}?_step={args.fork_step}"
        logger.info(f"Setting fork_from = {fork_from}")

    experiment = Experiment(
        num_steps=args.steps,
        num_metrics=args.num_metrics,
        metric_key_size=args.metric_key_size,
        output_file=args.outfile,
        data_type=args.data_type,
        is_unique_payload=args.unique_payload,
        time_delay_second=args.time_delay_second,
        run_id=args.run_id,
        resume_mode=args.resume_mode,
        fraction=args.fraction,
        dense_metric_count=args.dense_metric_count,
        fork_from=fork_from,
        project=args.project,
        sparse_stride_size=args.sparse_stride_size,
        starting_global_step=args.global_step,
        mode=args.mode,
    )

    experiment.parallel_runs(args.parallel)
