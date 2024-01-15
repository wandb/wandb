import os
import random
import string
import tempfile
import typing
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio
import pytest
import wandb
import wandb.apis.reports as wr
from PIL import Image
from rdkit import Chem

LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"


def get_free_port():
    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    return str(sock.getsockname()[1])


@dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: str = FIXTURE_SERVICE_PORT
    method: Literal["post"] = "post"


@dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: str = SERVICES_API_PORT
    method: Literal["put"] = "put"


@dataclass
class WandbServerSettings:
    name: str
    volume: str
    local_base_port: str
    services_api_port: str
    fixture_service_port: str
    db_port: str
    wandb_server_pull: str
    wandb_server_tag: str
    internal_local_base_port: str = "8080"
    internal_local_services_api_port: str = "8083"
    internal_fixture_service_port: str = "9015"
    internal_db_port: str = "3306"
    url: str = "http://localhost"

    base_url: Optional[str] = None

    def __post_init__(self):
        self.base_url = f"{self.url}:{self.local_base_port}"


@dataclass
class WandbLoggingConfig:
    n_steps: int
    n_metrics: int
    n_experiments: int
    n_reports: int

    project_name: str = "test"


@dataclass
class WandbServerUser:
    server: WandbServerSettings
    user: str


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def wandb_logging_config():
    return WandbLoggingConfig(
        n_steps=100,
        n_metrics=2,
        n_experiments=1,
        n_reports=1,
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
            art2 = make_artifact("used_art")
            run.log_artifact(art)
            run.use_artifact(art2)

    # create reports
    for _ in range(wandb_logging_config.n_reports):
        wr.Report(
            project=wandb_logging_config.project_name,
            blocks=[wr.H1("blah")],
        ).save()

    # # Create special artifacts
    # with wandb.init(
    #     id="artifact-gaps",
    #     project="artifact-gaps",
    #     settings={"console": "off", "save_code": False},
    # ) as run:
    #     n_arts = 1
    #     # Create artifact versions
    #     for i in range(n_arts):
    #         fname = str(i)
    #         art = wandb.Artifact("gap", "gap")
    #         with open(fname, "w"):
    #             pass
    #         art.add_file(fname)
    #         run.log_artifact(art)

    # Then randomly delete some artifacts to make gaps
    # api = wandb.Api()
    # art_type = api.artifact_type("gap", "artifact-gaps")
    # for collection in art_type.collections():
    #     for art in collection.artifacts():
    #         v = int(art.version[1:])
    #         if v in (0, 2):
    #             art.delete(delete_aliases=True)

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
