import argparse
import json
import logging
import multiprocessing as mp
import random
import string
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal

import numpy as np
import wandb

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
    """

    def __init__(
        self,
        data_type: Literal[
            "scalar", "audio", "video", "image", "table", "prefixed_scalar"
        ],
        sparse_metric_count: int,
        metric_key_size: int,
        num_steps: int,
        fraction: float,
        is_unique_payload: bool,
        dense_metric_count: int,
    ):
        self.data_type = data_type
        self.sparse_metric_count = sparse_metric_count
        self.metric_key_size = metric_key_size
        self.num_steps = num_steps
        self.fraction = fraction
        self.is_unique_payload = is_unique_payload
        self.dense_metric_count = dense_metric_count

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

    def generate(self) -> List[dict]:
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

    def generate_audio(self) -> List[dict[str, wandb.Audio]]:
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

    def generate_scalar(self) -> List[dict[str, int]]:
        """Generates the payloads for logging scalar data.

        Returns:
            List: A list of dictionaries with the scalar data.
        """
        # Generate dense metrics if applicable
        dense_metrics = (
            {
                self.random_string(self.metric_key_size): random.randint(1, 10**2)
                for _ in range(self.dense_metric_count)
            }
            if self.dense_metric_count > 0
            else {}
        )

        # Log example dense metric if available
        if dense_metrics:
            example_key = next(iter(dense_metrics))
            logger.info(f"Example dense metric: {example_key}")

        # Generate base payloads with optional dense metrics prepended
        payloads = [
            {
                **dense_metrics,
                **{
                    self.random_string(self.metric_key_size): random.randint(1, 10**2)
                    for _ in range(self.metrics_count_per_step)
                },
            }
            for _ in range(self.num_of_unique_payload)
        ]

        return payloads

    def generate_prefixed_scalar(self) -> List[dict[str, int]]:
        """Generates the payloads for logging scalar data with prefixes.

           This makes all the runs in the same project to have the repeating metric names.

        Returns:
            List: A list of dictionaries with the scalar data.
        """
        # Generate dense metrics if applicable
        dense_metrics = (
            {
                f"dense/accuracy{i}": random.randint(1, 10**2)
                for i in range(self.dense_metric_count)
            }
            if self.dense_metric_count > 0
            else {}
        )

        # Log example dense metric if available
        if dense_metrics:
            example_key = next(iter(dense_metrics))
            logger.info(f"Example dense metric: {example_key}")

        # Generate base payloads with optional dense metrics prepended
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

    def generate_table(self) -> List[dict[str, wandb.Table]]:
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

            columns = [f"Field_{i+1}" for i in range(num_of_columns)]
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

    def generate_image(self) -> List[dict[str, wandb.Image]]:
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

    def generate_video(self) -> List[dict[str, wandb.Video]]:
        """Generates a payload for logging videos.

        Returns:
            List: A list of dictionary with video data.
        """
        payloads = []
        for _ in range(self.num_of_unique_payload):
            # Create a random video (50 frames, 64x64 pixels, 3 channels for RGB)
            frames = np.random.randint(0, 256, (50, 64, 64, 3), dtype=np.uint8)
            video_obj = wandb.Video(frames, fps=10, caption="Randomly generated video")

            payloads.append(
                {
                    self.random_string(self.metric_key_size): video_obj
                    for _ in range(self.sparse_metric_count)
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

    When to set "is_unique_payload" to True?

    Performance benchmarks are usually done on the basic use case to form the baseline, then on top
    of it, scale tests of various dimensions are run (# of steps, # of metrics, metric size, etc) to
    characterize its scalability.

    For benchmarks or regression detection testings, set is_unique_payload to False (default). For stress
    testings or simulating huge workload w/ million+ metrics, set is_unique_payload to True.
    """

    def __init__(
        self,
        num_steps: int = 10,
        num_metrics: int = 100,
        metric_key_size: int = 10,
        output_file: str = "results.json",
        data_type: Literal[
            "scalar", "audio", "video", "image", "table", "prefixed_scalar"
        ] = "scalar",
        is_unique_payload: bool = False,
        time_delay_second: float = 0.0,
        run_id: str = "",
        resume_mode: str = "must",
        fraction: float = 1.0,
        dense_metric_count: int = 0,
        fork_from: str = "",
        project: str = "perf-test",
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
            if self.run_id == "":
                if self.fork_from == "":
                    run = wandb.init(
                        project=self.project,
                        name=f"perf_run={start_time_str}_steps={self.num_steps}_metrics={self.num_metrics}",
                        config=result_data,
                    )
                else:
                    run = wandb.init(
                        project=self.project,
                        name=f"perf_run={start_time_str}_steps={self.num_steps}_metrics={self.num_metrics}",
                        config=result_data,
                        fork_from=self.fork_from,
                        settings=wandb.Settings(init_timeout=600),
                    )
                logger.info(f"New run {run.id} initialized")

            else:
                logger.info(f"Resuming run {self.run_id} with {self.resume_mode}.")
                run = wandb.init(
                    project=self.project,
                    id=self.run_id,
                    resume=self.resume_mode,
                )

            result_data["init_time"] = timer.stop()

        # pre-generate all the payloads
        logger.info("Generating test payloads ...")
        payloads = PayloadGenerator(
            self.data_type,
            self.num_metrics,
            self.metric_key_size,
            self.num_steps,
            self.fraction,
            self.is_unique_payload,
            self.dense_metric_count,
        ).generate()

        logger.info(f"Start logging {self.num_steps} steps ...")
        with Timer() as timer:
            for s in range(self.num_steps):
                if self.is_unique_payload or self.fraction < 1.0:
                    run.log(payloads[s % len(payloads)])
                else:
                    run.log(payloads[0])

                # 12/20/2024 - Wai
                # HACKAROUND: We ran into some 500s and 502s errors when SDK logs
                # a million+ unique metrics in a tight loop. Adding a small sleep
                # between each step works around the problem for now.
                if self.time_delay_second > 0:
                    time.sleep(self.time_delay_second)

            result_data["log_time"] = timer.stop()

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


def run_parallel_experiment(
    *,
    num_processes: int,
    num_steps: int,
    num_metrics: int,
    data_type: Literal["scalar", "audio", "video", "image", "table", "prefixed_scalar"],
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
        help="The number of sparse metrics to log per step (optional: "
        "use together with -f to control %).",
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
        default="",
        help="The run id. e.g. -i 123abc to resume this run id.",
    )

    parser.add_argument(
        "-j",
        "--resume-mode",
        type=str,
        choices=["must", "allow", "never"],
        default="must",
        help="Use with --run-id. The resume mode.",
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

    args = parser.parse_args()

    fork_from_str = ""
    if args.fork_run_id:
        fork_from_str = f"{args.fork_run_id}?_step={args.fork_step}"
        logger.info(f"Setting fork_from = {fork_from_str}")

    Experiment(
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
        fork_from=fork_from_str,
        project=args.project,
    ).run(args.repeat)
