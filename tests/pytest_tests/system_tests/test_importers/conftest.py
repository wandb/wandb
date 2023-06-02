import os
import signal
import subprocess
import tempfile
import time
import urllib.parse
import uuid
import warnings
from itertools import islice
from typing import Any, Dict, Iterable, List, Optional

import hypothesis.strategies as st
import mlflow
import psutil
import pytest
import requests
from hypothesis.errors import NonInteractiveExampleWarning
from mlflow.entities import Metric
from mlflow.tracking import MlflowClient
from packaging.version import Version

MLFLOW_BASE_URL = "http://localhost:4040"
MLFLOW_HEALTH_ENDPOINT = "health"
EXPERIMENTS = 2
RUNS_PER_EXPERIMENT = 3
STEPS = 1000
N_ROOT_FILES = 5
N_SUBDIRS = 3
N_SUBDIR_FILES = 2
LOGGING_BATCH_SIZE = 50

SECONDS_FROM_2023_01_01 = 1672549200

mlflow_version = Version(mlflow.__version__)

Path = str


def _make_run(
    name: Optional[str] = None,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, float]] = None,
    metrics: Optional[Iterable[Dict[str, float]]] = None,
    artifacts_dir: Optional[Path] = None,
    batch_size: Optional[int] = None,
):
    client = MlflowClient()
    with mlflow.start_run() as run:
        if name:
            mlflow.set_tag("mlflow.runName", name)
        if tags:
            mlflow.set_tags(tags)
        if params:
            mlflow.log_params(params)
        if metrics:
            if batch_size:
                for batch in batch_metrics(metrics, batch_size):
                    client.log_batch(run.info.run_id, metrics=batch)
            else:
                for m in metrics:
                    mlflow.log_metrics(m)
        if artifacts_dir:
            mlflow.log_artifact(artifacts_dir)


# def make_nested_run():
#     with mlflow.start_run():
#         for _ in range(NUM_RUNS_PER_NESTED_EXPERIMENT):
#             make_run(batch_size=50)


def batched(n, iterable):
    i = iter(iterable)
    batch = list(islice(i, n))
    while batch:
        yield batch
        batch = list(islice(i, n))


def batch_metrics(metrics, bs: int) -> Iterable[List[Metric]]:
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
        }


def make_artifacts_dir(
    root_dir: Path, n_root_files: int, n_subdirs: int, n_subdir_files: int
) -> Path:
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


def make_run(name, n_steps, mlflow_batch_size, n_root_files, n_subdirs, n_subdir_files):
    with tempfile.TemporaryDirectory() as temp_path:
        _make_run(
            name=name,
            tags=make_tags(),
            params=make_params(),
            metrics=make_metrics(n_steps),
            artifacts_dir=make_artifacts_dir(
                temp_path, n_root_files, n_subdirs, n_subdir_files
            ),
            batch_size=mlflow_batch_size,
        )


def make_exp(
    n_runs, n_steps, mlflow_batch_size, n_root_files, n_subdirs, n_subdir_files
):
    exp_name = "Experiment " + str(uuid.uuid4())
    mlflow.set_experiment(exp_name)

    # Can't use ProcessPoolExecutor -- it seems to always fail in tests!
    for _ in range(n_runs):
        run_name = "Run :/" + str(uuid.uuid4())
        make_run(
            run_name,
            n_steps,
            mlflow_batch_size,
            n_root_files,
            n_subdirs,
            n_subdir_files,
        )


def log_to_mlflow(
    mlflow_tracking_uri: str,
    n_exps: int = 2,
    n_runs_per_exp: int = 3,
    n_steps: int = 1000,
    mlflow_batch_size: int = 50,
    n_root_files: int = 3,
    n_subdirs: int = 3,
    n_subdir_files: int = 2,
):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=NonInteractiveExampleWarning)
        mlflow.set_tracking_uri(mlflow_tracking_uri)

        # Can't use ProcessPoolExecutor -- it seems to always fail in tests!
        for _ in range(n_exps):
            make_exp(
                n_runs_per_exp,
                n_steps,
                mlflow_batch_size,
                n_root_files,
                n_subdirs,
                n_subdir_files,
            )


def check_mlflow_server_health(
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


def kill_child_processes(parent_pid, sig=signal.SIGTERM):
    try:
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for process in children:
        process.send_signal(sig)


@pytest.fixture
def mssql_backend():
    ...


@pytest.fixture
def mysql_backend():
    ...


@pytest.fixture
def postgres_backend():
    ...


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


def get_free_port():
    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    return str(sock.getsockname()[1])


@pytest.fixture()
def mlflow_server(mlflow_backend, mlflow_artifacts_destination):
    new_port = get_free_port()
    modified_base_url = MLFLOW_BASE_URL.replace("4040", new_port)

    if mlflow_version < Version("2.0.0"):
        start_cmd = [
            "mlflow",
            "server",
            "-p",
            new_port,
            # no sqlite
            # no --artifacts-destination flag
        ]
    else:
        start_cmd = [
            "mlflow",
            "server",
            "-p",
            new_port,
            "--backend-store-uri",
            mlflow_backend,
            "--artifacts-destination",
            mlflow_artifacts_destination,
        ]

    process = subprocess.Popen(start_cmd)  # process
    healthy = check_mlflow_server_health(
        modified_base_url, MLFLOW_HEALTH_ENDPOINT, num_retries=30
    )

    if healthy:
        yield modified_base_url
    else:
        raise Exception("MLflow server is not healthy")

    kill_child_processes(process.pid)


@pytest.fixture
def prelogged_mlflow_server(mlflow_server):
    log_to_mlflow(
        mlflow_server,
        EXPERIMENTS,
        RUNS_PER_EXPERIMENT,
        STEPS,
        LOGGING_BATCH_SIZE,
        N_ROOT_FILES,
        N_SUBDIRS,
        N_SUBDIR_FILES,
    )

    total_runs = EXPERIMENTS * RUNS_PER_EXPERIMENT
    total_files = N_ROOT_FILES + N_SUBDIRS * N_SUBDIR_FILES

    yield mlflow_server, total_runs, total_files, STEPS
