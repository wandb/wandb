import os
import random
import string
import subprocess
import tempfile
import typing

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio
import pytest
import wandb
import wandb.apis.reports as wr
from PIL import Image
from rdkit import Chem

from ...utils import WandbServerSettings, spin_wandb_server

# `local-testcontainer2` ports
LOCAL_BASE_PORT2 = "9180"
SERVICES_API_PORT2 = "9183"
FIXTURE_SERVICE_PORT2 = "9115"

DEFAULT_SERVER_CONTAINER_NAME2 = "wandb-local-testcontainer2"
DEFAULT_SERVER_VOLUME2 = "wandb-local-testcontainer-vol2"


def pytest_addoption(parser):
    parser.addoption(
        "--wandb-second-server",
        default=True,
        help="Spin up a second server (for importer tests)",
    )


def pytest_configure(config):
    # start or connect to wandb test server2 (for importer tests)
    # this is here because and not in the `system_tests/test_importers/conftest.py`
    # because when it was included there, the wandb-local-testcontainer (from this conf)
    # did not spin up when testing the importers dir specifically
    if config.getoption("--wandb-second-server"):
        settings2 = WandbServerSettings(
            name=DEFAULT_SERVER_CONTAINER_NAME2,
            volume=DEFAULT_SERVER_VOLUME2,
            local_base_port=LOCAL_BASE_PORT2,
            services_api_port=SERVICES_API_PORT2,
            fixture_service_port=FIXTURE_SERVICE_PORT2,
            wandb_server_pull=config.getoption("--wandb-server-pull"),
            wandb_server_image_registry=config.getoption(
                "--wandb-server-image-registry"
            ),
            wandb_server_image_repository=config.getoption(
                "--wandb-server-image-repository"
            ),
            wandb_server_tag=config.getoption("--wandb-server-tag"),
            wandb_server_use_existing=config.getoption(
                "--wandb-server-use-existing",
                default=True if os.getenv("CI") else False,
            ),
        )
        config.wandb_server_settings2 = settings2

        success2 = spin_wandb_server(settings2)
        if not success2:
            pytest.exit("Failed to connect to wandb server2")


def pytest_unconfigure(config):
    clean = config.getoption("--wandb-server-clean")
    if clean != "none":
        print("Cleaning up wandb server...")
    if clean in ("container", "all"):
        print(
            f"Cleaning up wandb server container ({config.wandb_server_settings.name}) ..."
        )
        command = ["docker", "rm", "-f", config.wandb_server_settings.name]
        subprocess.run(command, check=True)

        if config.getoption("--wandb-second-server"):
            print(
                f"Cleaning up wandb server container2 ({config.wandb_server_settings2.name}) ..."
            )
            command = ["docker", "rm", "-f", config.wandb_server_settings2.name]
            subprocess.run(command, check=True)
    if clean in ("volume", "all"):
        print(
            f"Cleaning up wandb server volume ({config.wandb_server_settings.volume}) ..."
        )
        command = ["docker", "volume", "rm", config.wandb_server_settings.volume]
        subprocess.run(command, check=True)

        if config.getoption("--wandb-second-server"):
            print(
                f"Cleaning up wandb server volume2 ({config.wandb_server_settings2.volume}) ..."
            )
            command = ["docker", "volume", "rm", config.wandb_server_settings2.volume]
            subprocess.run(command, check=True)


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def fixture_fn2(request, fixture_fn_factory):
    yield from fixture_fn_factory(request.config.wandb_server_settings2)


@pytest.fixture(scope=determine_scope)
def user2(request, user_factory, fixture_fn2):
    yield from user_factory(fixture_fn2, request.config.wandb_server_settings2)


@pytest.fixture
def server_src(user):
    n_experiments = 2
    n_steps = 50
    n_metrics = 3
    n_reports = 2
    project_name = "test"

    for _ in range(n_experiments):
        run = wandb.init(entity=user, project=project_name)

        # log metrics
        data = generate_random_data(n_steps, n_metrics)
        for i in range(n_steps):
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

        # log artifacts
        for _ in range(3):
            # make 3 here and later delete the middle one to test gap handling
            art = make_artifact("logged_art")
            run.log_artifact(art)

        art2 = make_artifact("used_art")
        run.use_artifact(art2)
        run.finish()

        # delete the middle artifact in sequence to test gap handling
        api = wandb.Api()
        art_type = api.artifact_type("logged_art", project_name)
        for collection in art_type.collections():
            for art in collection.artifacts():
                v = int(art.version[1:])
                if v == 1:
                    wandb.termwarn(f"DELETING THIS ARTIFACT {art=}")
                    art.delete(delete_aliases=True)

    # create reports
    for _ in range(n_reports):
        wr.Report(project=project_name, blocks=[wr.H1("blah")]).save()


def generate_random_data(n: int, n_metrics: int) -> list:
    steps = np.arange(1, n + 1, 1)
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
    with tempfile.TemporaryDirectory() as tmpdirname:
        filename = os.path.join(tmpdirname, "random_text.txt")

        with open(filename, "w") as f:
            for _ in range(100):  # Write 100 lines of 50 random chars
                random_text = generate_random_text(50)
                f.write(random_text + "\n")

        print(f"Random text data has been written to {filename}")

        artifact = wandb.Artifact(name, name)
        artifact.add_file(filename)
        return artifact
