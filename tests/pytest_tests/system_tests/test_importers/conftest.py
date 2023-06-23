import os
import random
import secrets
import signal
import string
import subprocess
import tempfile
import time
import typing
import urllib.parse
import uuid
import warnings
from dataclasses import dataclass
from itertools import islice
from typing import Any, Dict, Iterable, List, Optional

import hypothesis.strategies as st
import mlflow
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio
import psutil
import pytest
import requests
import wandb
from hypothesis.errors import NonInteractiveExampleWarning
from mlflow.entities import Metric
from mlflow.tracking import MlflowClient
from packaging.version import Version
from PIL import Image
from rdkit import Chem

from ..helpers import (
    WandbServerSettings,
)

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


def random_string(length: int = 12) -> str:
    """Generate a random string of a given length.

    :param length: Length of the string to generate.
    :return: Random string.
    """
    return "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


@dataclass
class WandbLoggingConfig:
    n_steps: int
    n_metrics: int
    n_experiments: int


@pytest.fixture(scope="session")
def wandb_logging_config():
    config = {"n_steps": 250, "n_metrics": 2, "n_experiments": 3}
    return WandbLoggingConfig(**config)


@pytest.fixture(scope="session")
def settings():
    src_server_settings = {
        "name": "wandb-src-server",
        "volume": "wandb-src-server-vol",
        "local_base_port": "9180",
        "services_api_port": "9183",
        "fixture_service_port": "9115",
        "wandb_server_pull": "missing",
        "wandb_server_tag": "master",
    }
    return WandbServerSettings(**src_server_settings)


@pytest.fixture(scope="session")
def wandb_server(wandb_server_factory, settings):
    return wandb_server_factory(settings)


@pytest.fixture(scope="session")
def alt_user(user_factory, fixture_fn_alt, settings):
    yield from user_factory(fixture_fn_alt, settings)


@pytest.fixture(scope="session")
def fixture_fn_alt(fixture_fn_factory, settings):
    yield from fixture_fn_factory(settings)


@pytest.fixture
def prelogged_wandb_server(wandb_server, alt_user, wandb_logging_config):
    for _ in range(wandb_logging_config.n_experiments):
        with wandb.init(
            project="test", settings={"console": "off", "save_code": False}
        ) as run:
            data = generate_random_data(
                wandb_logging_config.n_steps, wandb_logging_config.n_metrics
            )
            for i in range(wandb_logging_config.n_steps):
                metrics = {k: v[i] for k, v in data.items()}
                run.log(metrics)

            run.log(
                {
                    "df": create_random_dataframe(),
                    "img": create_random_image(),
                    # "vid": create_random_video(),  # path error matplotlib
                    "audio": create_random_audio(),
                    "pc": create_random_point_cloud(),
                    "html": create_random_html(),
                    "plotly_fig": create_random_plotly(),
                    "mol": create_random_molecule(),
                }
            )

    return alt_user


def generate_random_data(n: int, n_metrics: int) -> list:
    steps = np.arange(0, n, 1)
    data = {}
    fns: list[typing.Any] = [
        lambda steps: steps**2,
        lambda steps: np.cos(steps * 0.0001),
        lambda steps: np.sin(steps * 0.01),
        lambda steps: np.log(steps + 1),
        lambda steps: np.exp(steps * 0.0001),
        lambda steps: np.exp(-steps * 0.0001) * 1000,  # Simulate decreasing loss
        lambda steps: 1 - np.exp(-steps * 0.0001),  # Simulate increasing accuracy
        lambda steps: np.power(steps, -0.5)
        * 1000,  # Simulate decreasing loss with power-law decay
        lambda steps: np.tanh(
            steps * 0.0001
        ),  # Simulate a metric converging to a value
        lambda steps: np.arctan(
            steps * 0.0001
        ),  # Simulate a metric converging to a value with a different curve
        lambda steps: np.piecewise(
            steps,
            [steps < n / 2, steps >= n / 2],
            [lambda steps: steps * 0.001, lambda steps: 1 - np.exp(-steps * 0.0001)],
        ),  # Simulate a two-stage training process
        lambda steps: np.sin(steps * 0.001)
        * np.exp(-steps * 0.0001),  # Sinusoidal oscillations with exponential decay
        lambda steps: (np.cos(steps * 0.001) + 1)
        * 0.5
        * (
            1 - np.exp(-steps * 0.0001)
        ),  # Oscillations converging to increasing accuracy
        lambda steps: np.log(steps + 1)
        * (
            1 - np.exp(-steps * 0.0001)
        ),  # Logarithmic growth modulated by increasing accuracy
        lambda steps: np.random.random()
        * (
            1 - np.exp(-steps * 0.0001)
        ),  # Random constant value modulated by increasing accuracy
    ]
    for j in range(n_metrics):
        noise_fraction = random.random()
        fn = random.choice(fns)
        values = fn(steps)
        # Add different types of noise
        noise_type = random.choice(["uniform", "normal", "triangular"])
        if noise_type == "uniform":
            noise = np.random.uniform(low=-noise_fraction, high=noise_fraction, size=n)
        elif noise_type == "normal":
            noise = np.random.normal(scale=noise_fraction, size=n)
        elif noise_type == "triangular":
            noise = np.random.triangular(
                left=-noise_fraction, mode=0, right=noise_fraction, size=n
            )
        data[f"metric{j}"] = values + noise_fraction * values * noise
    return data


# Function to generate random text
def generate_random_text(length=10):
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def create_random_dataframe(rows=100, columns=5):
    data = np.random.randint(0, 100, (rows, columns))
    df = pd.DataFrame(data)
    return df


def create_random_image(size=(100, 100)):
    array = np.random.randint(0, 256, size + (3,), dtype=np.uint8)
    img = Image.fromarray(array)
    return wandb.Image(img)


def create_random_video():
    frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
    return wandb.Video(frames, fps=4)


def create_random_audio():
    # Generate a random numpy array for audio data
    sampling_rate = 44100  # Typical audio sampling rate
    duration = 1.0  # duration in seconds
    audio_data = np.random.uniform(
        low=-1.0, high=1.0, size=int(sampling_rate * duration)
    )
    return wandb.Audio(audio_data, sample_rate=sampling_rate, caption="its audio yo")


def create_random_plotly():
    df = pd.DataFrame({"x": np.random.rand(100), "y": np.random.rand(100)})

    # Create a scatter plot
    fig = px.scatter(df, x="x", y="y")
    return fig


def create_random_html():
    fig = create_random_plotly()
    string = pio.to_html(fig)
    return wandb.Html(string)


def create_random_point_cloud():
    point_cloud = np.random.rand(100, 3)
    return wandb.Object3D(point_cloud)


def create_random_molecule():
    m = Chem.MolFromSmiles("Cc1ccccc1")
    return wandb.Molecule.from_rdkit(m)


def make_artifact(name):
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as tmpdirname:

        # Set the filename
        filename = os.path.join(tmpdirname, "random_text.txt")

        # Open the file in write mode
        with open(filename, "w") as f:
            for _ in range(100):  # Write 100 lines of random text
                random_text = generate_random_text(
                    50
                )  # Each line contains 50 characters
                f.write(random_text + "\n")  # Write the random text to the file

        print(f"Random text data has been written to {filename}")

        # Create a new artifact
        artifact = wandb.Artifact(name, name)

        # Add the file to the artifact
        artifact.add_file(filename)
        return artifact
