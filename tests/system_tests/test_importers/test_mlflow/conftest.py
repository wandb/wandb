from __future__ import annotations

import os
import subprocess
import tempfile
import time
import urllib.parse
import uuid
import warnings
from collections.abc import Iterable
from dataclasses import dataclass

import hypothesis.strategies as st
import mlflow
import pytest
import requests
from hypothesis.errors import NonInteractiveExampleWarning
from mlflow.entities import Metric
from mlflow.tracking import MlflowClient
from packaging.version import Version
from wandb.util import batched

SECONDS_FROM_2023_01_01 = 1672549200

mlflow_version = Version(mlflow.__version__)

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


@dataclass
class MlflowServerSettings:
    metrics_backend: Literal[
        "mssql_backend",
        "mysql_backend",
        "postgres_backend",
        "file_backend",
        "sqlite_backend",
    ]
    artifacts_backend: Literal["file_artifacts", "s3_artifacts"]

    base_url: str = "http://localhost:4040"
    health_endpoint: str = "health"

    # helper if port is blocked
    new_port: str | None = None

    def __post_init__(self):
        self.new_port = self._get_free_port()
        self.base_url = self.base_url.replace("4040", self.new_port)

    @staticmethod
    def _get_free_port():
        import socket

        sock = socket.socket()
        sock.bind(("", 0))
        return str(sock.getsockname()[1])


@dataclass
class MlflowLoggingConfig:
    # experiments and metrics
    n_experiments: int
    n_runs_per_experiment: int
    n_steps_per_run: int

    # artifacts
    n_artifacts: int
    n_root_files: int
    n_subdirs: int
    n_subdir_files: int

    # batching
    logging_batch_size: int = 50

    @property
    def total_runs(self):
        return self.n_experiments * self.n_runs_per_experiment

    @property
    def total_files(self):
        return self.n_artifacts * (
            self.n_root_files + self.n_subdirs * self.n_subdir_files
        )


# def make_nested_run():
#     with mlflow.start_run():
#         for _ in range(NUM_RUNS_PER_NESTED_EXPERIMENT):
#             make_run(batch_size=50)


def batch_metrics(metrics, bs: int) -> Iterable[list[Metric]]:
    step = 0
    for i, batch in enumerate(batched(bs, metrics)):
        batched_metrics = []
        for step, metric in enumerate(batch, start=i * bs):
            for k, v in metric.items():
                batched_metrics.append(
                    Metric(k, v, step=step, timestamp=SECONDS_FROM_2023_01_01)
                )
        yield batched_metrics


def make_tags():
    return st.dictionaries(
        st.text(
            min_size=1,
            max_size=20,
            alphabet="abcdefghijklmnopqrstuvwxyz1234567890_- ",
        ),
        st.text(max_size=20),
        max_size=10,
    ).example()


def make_params():
    # Older versions have trouble handling certain kinds of strings and larger dicts
    if mlflow_version < Version("2.0.0"):
        param_str = st.text(
            max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz1234567890_- "
        ).example()
        param_dict = st.dictionaries(
            st.text(max_size=4, alphabet="abcdefghijklmnopqrstuvwxyz1234567890_- "),
            st.integers(),
            max_size=2,
        ).example()
    else:
        param_str = st.text(max_size=20).example()
        param_dict = st.dictionaries(
            st.text(max_size=20),
            st.integers(),
            max_size=10,
        ).example()

    return {
        "param_int": st.integers().example(),
        "param_float": st.floats().example(),
        "param_str": param_str,
        "param_bool": st.booleans().example(),
        "param_list": st.lists(st.integers()).example(),
        "param_dict": param_dict,
        "param_tuple": st.tuples(st.integers(), st.integers()).example(),
        "param_set": st.sets(st.integers()).example(),
        "param_none": None,
    }


def make_metrics(n_steps):
    for _ in range(n_steps):
        yield {
            "metric_int": st.integers(min_value=0, max_value=100).example(),
            "metric_float": st.floats(min_value=0, max_value=100).example(),
            "metric_bool": st.booleans().example(),
        }


def make_artifacts_dir(
    root_dir: str, n_root_files: int, n_subdirs: int, n_subdir_files: int
) -> str:
    # Ensure root_dir exists
    os.makedirs(root_dir, exist_ok=True)

    for i in range(n_root_files):
        file_path = os.path.join(root_dir, f"file{i}.txt")
        with open(file_path, "w") as f:
            f.write(f"text from {file_path}")

    for i in range(n_subdirs):
        subdir_path = os.path.join(root_dir, f"subdir{i}")
        os.makedirs(subdir_path, exist_ok=True)

        for j in range(n_subdir_files):
            file_path = os.path.join(subdir_path, f"file{j}.txt")
            with open(file_path, "w") as f:
                f.write(f"text from {file_path}")

    return root_dir


def _check_mlflow_server_health(
    base_url: str, endpoint: str, num_retries: int = 1, sleep_time: int = 1
):
    for _ in range(num_retries):
        try:
            response = requests.get(urllib.parse.urljoin(base_url, endpoint))
            if response.status_code == 200:
                return True
            time.sleep(sleep_time)
        except requests.exceptions.ConnectionError:
            time.sleep(sleep_time)
    return False


@pytest.fixture
def mssql_backend(): ...


@pytest.fixture
def mysql_backend(): ...


@pytest.fixture
def postgres_backend(): ...


@pytest.fixture
def file_backend(tmp_path):
    yield tmp_path / "mlruns"


@pytest.fixture
def sqlite_backend():
    yield "sqlite:///mlflow.db"


# https://github.com/pytest-dev/pytest/issues/349
@pytest.fixture(
    params=[
        # "mssql_backend",
        # "mysql_backend",
        # "postgres_backend",
        "file_backend",
        "sqlite_backend",
    ]
)
def mlflow_backend(request):
    yield request.getfixturevalue(request.param)


@pytest.fixture
def file_artifacts(tmp_path):
    yield tmp_path / "mlartifacts"


@pytest.fixture
def s3_artifacts():
    yield ...


@pytest.fixture(
    params=[
        "file_artifacts",
        # "s3_artifacts",
    ]
)
def mlflow_artifacts_destination(request):
    yield request.getfixturevalue(request.param)


@pytest.fixture
def mlflow_server_settings(mlflow_artifacts_destination, mlflow_backend):
    return MlflowServerSettings(
        metrics_backend=mlflow_backend,
        artifacts_backend=mlflow_artifacts_destination,
    )


@pytest.fixture
def mlflow_logging_config():
    return MlflowLoggingConfig(
        # run settings
        n_experiments=1,
        n_runs_per_experiment=2,
        n_steps_per_run=100,
        # artifact settings
        n_artifacts=2,
        n_root_files=5,
        n_subdirs=3,
        n_subdir_files=2,
    )


@pytest.fixture
def mlflow_server(mlflow_server_settings):
    if mlflow_version < Version("2.0.0"):
        start_cmd = [
            "mlflow",
            "server",
            "-p",
            mlflow_server_settings.new_port,
            # no sqlite
            # no --artifacts-destination flag
        ]
    else:
        start_cmd = [
            "mlflow",
            "server",
            "-p",
            mlflow_server_settings.new_port,
            "--backend-store-uri",
            mlflow_server_settings.metrics_backend,
            "--artifacts-destination",
            mlflow_server_settings.artifacts_backend,
        ]

    _ = subprocess.Popen(start_cmd)  # process
    healthy = _check_mlflow_server_health(
        mlflow_server_settings.base_url,
        mlflow_server_settings.health_endpoint,
        num_retries=30,
    )

    if healthy:
        yield mlflow_server_settings
    else:
        raise Exception("MLflow server is not healthy")


@pytest.fixture
def prelogged_mlflow_server(mlflow_server, mlflow_logging_config):
    config = mlflow_logging_config

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=NonInteractiveExampleWarning)
        mlflow.set_tracking_uri(mlflow_server.base_url)

        # Experiments
        for _ in range(config.n_experiments):
            exp_name = "Experiment " + str(uuid.uuid4())
            mlflow.set_experiment(exp_name)

            # Runs
            for _ in range(config.n_runs_per_experiment):
                run_name = "Run " + str(uuid.uuid4())
                client = MlflowClient()
                with mlflow.start_run() as run:
                    mlflow.set_tag("mlflow.runName", run_name)
                    mlflow.set_tags(make_tags())
                    mlflow.set_tag("longTag", "abcd" * 100)
                    mlflow.log_params(make_params())

                    metrics = make_metrics(config.n_steps_per_run)
                    for batch in batch_metrics(metrics, config.logging_batch_size):
                        client.log_batch(run.info.run_id, metrics=batch)

                    for _ in range(config.n_artifacts):
                        with tempfile.TemporaryDirectory() as temp_path:
                            artifacts_dir = make_artifacts_dir(
                                temp_path,
                                config.n_root_files,
                                config.n_subdirs,
                                config.n_subdir_files,
                            )
                            mlflow.log_artifact(artifacts_dir)

    return mlflow_server
