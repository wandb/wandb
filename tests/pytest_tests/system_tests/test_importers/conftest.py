import os
import random
import signal
import string
import subprocess
import tempfile
import time
import typing
import urllib.parse
import uuid
import warnings
from typing import Iterable, List

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
import wandb.apis.reports as wr
from hypothesis.errors import NonInteractiveExampleWarning
from mlflow.entities import Metric
from mlflow.tracking import MlflowClient
from packaging.version import Version
from PIL import Image
from rdkit import Chem
from wandb.util import batched

from ..helpers import (
    MlflowLoggingConfig,
    MlflowServerSettings,
    WandbLoggingConfig,
    WandbServerSettings,
    WandbServerUser,
)

SECONDS_FROM_2023_01_01 = 1672549200

mlflow_version = Version(mlflow.__version__)


# def make_nested_run():
#     with mlflow.start_run():
#         for _ in range(NUM_RUNS_PER_NESTED_EXPERIMENT):
#             make_run(batch_size=50)


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


def _kill_child_processes(parent_pid, sig=signal.SIGTERM):
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


@pytest.fixture
def mlflow_server_settings(mlflow_artifacts_destination, mlflow_backend):
    return MlflowServerSettings(
        metrics_backend=mlflow_backend,
        artifacts_backend=mlflow_artifacts_destination,
    )


@pytest.fixture
def mlflow_logging_config():
    return MlflowLoggingConfig(
        n_experiments=2,
        n_runs_per_experiment=3,
        n_steps_per_run=1000,
        n_root_files=5,
        n_subdirs=3,
        n_subdir_files=2,
    )


@pytest.fixture
def new_mlflow_server(mlflow_server_settings):
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

    process = subprocess.Popen(start_cmd)  # process
    healthy = _check_mlflow_server_health(
        mlflow_server_settings.base_url,
        mlflow_server_settings.health_endpoint,
        num_retries=30,
    )

    if healthy:
        yield mlflow_server_settings
    else:
        raise Exception("MLflow server is not healthy")

    _kill_child_processes(process.pid)


@pytest.fixture
def new_prelogged_mlflow_server(new_mlflow_server, mlflow_logging_config):
    config = mlflow_logging_config

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=NonInteractiveExampleWarning)
        mlflow.set_tracking_uri(new_mlflow_server.base_url)

        # Experiments
        for _ in range(config.n_experiments):
            exp_name = "Experiment " + str(uuid.uuid4())
            mlflow.set_experiment(exp_name)

            # Runs
            for _ in range(config.n_runs_per_experiment):
                run_name = "Run :/" + str(uuid.uuid4())
                client = MlflowClient()
                with mlflow.start_run() as run:
                    mlflow.set_tag("mlflow.runName", run_name)
                    mlflow.set_tags(make_tags())
                    mlflow.log_params(make_params())

                    metrics = make_metrics(config.n_steps_per_run)
                    for batch in batch_metrics(metrics, config.logging_batch_size):
                        client.log_batch(run.info.run_id, metrics=batch)

                    with tempfile.TemporaryDirectory() as temp_path:
                        artifacts_dir = make_artifacts_dir(
                            temp_path,
                            config.n_root_files,
                            config.n_subdirs,
                            config.n_subdir_files,
                        )
                        mlflow.log_artifact(artifacts_dir)

    return new_mlflow_server


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def wandb_logging_config():
    return WandbLoggingConfig(
        n_steps=100,
        n_metrics=2,
        n_experiments=3,
        n_reports=3,
    )


@pytest.fixture(scope="session")
def wandb_server2(wandb_server_factory):
    settings = WandbServerSettings(
        name="wandb-src-server",
        volume="wandb-src-server-vol",
        local_base_port="9180",
        services_api_port="9183",
        fixture_service_port="9115",
        db_port="3307",
        wandb_server_pull="missing",
        wandb_server_tag="master",
    )

    wandb_server_factory(settings)
    return settings


@pytest.fixture(scope=determine_scope)
def user2(user_factory, fixture_fn2, wandb_server2):
    yield from user_factory(fixture_fn2, wandb_server2)


@pytest.fixture(scope="session")
def fixture_fn2(wandb_server2, fixture_fn_factory):
    yield from fixture_fn_factory(wandb_server2)


@pytest.fixture
def wandb_server_dst(wandb_server, user):
    return WandbServerUser(wandb_server, user)


@pytest.fixture
def wandb_server_src(wandb_server2, user2, wandb_logging_config):
    for _ in range(wandb_logging_config.n_experiments):
        with wandb.init(
            project=wandb_logging_config.project_name,
            settings={"console": "off", "save_code": False},
        ) as run:
            # log metrics
            data = generate_random_data(
                wandb_logging_config.n_steps, wandb_logging_config.n_metrics
            )
            for i in range(wandb_logging_config.n_steps):
                metrics = {k: v[i] for k, v in data.items()}
                run.log(metrics)

            # log tables
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

            art = make_artifact("logged_art")
            # art2 = make_artifact("used_art")
            run.log_artifact(art)
            # run.use_artifact(art2)

    # create reports
    for _ in range(wandb_logging_config.n_reports):
        wr.Report(
            project=wandb_logging_config.project_name,
            blocks=[wr.H1("blah")],
        ).save()

    return WandbServerUser(wandb_server2, user2)


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
