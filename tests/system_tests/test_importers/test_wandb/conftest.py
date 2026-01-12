from __future__ import annotations

import logging
import os
import random
import string
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


@pytest.fixture
def user2(backend_importers_fixture_factory):
    return backend_importers_fixture_factory.make_user()


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
        for _ in range(2):
            art = make_artifact("logged_art")
            run.log_artifact(art)
            # art.wait()
            # print(f"Logged artifact {run.name=}, {art.version=}")

        art2 = make_artifact("used_art")
        run.use_artifact(art2)
        run.finish()

        # log to terminal
        logging.info("Example log line")

        # TODO: We should be testing for gaps in artifact sequences (e.g. if an artifact was deleted).
        # In manual tests it does work, but it seems to misbehave in the testcontainer, so commenting
        # this out for now.
        # delete the middle artifact in sequence to test gap handling
        # api = wandb.Api()
        # art_type = api.artifact_type("logged_art", project_name)
        # for collection in art_type.collections():
        #     for art in collection.artifacts():
        #         v = int(art.version[1:])
        #         if v == 1:
        #             art.delete(delete_aliases=True)

    # create reports
    for _ in range(n_reports):
        wr.Report(project=project_name, blocks=[wr.H1("blah")]).save()


def generate_random_data(n: int, n_metrics: int) -> list:
    rng = np.random.RandomState(seed=1337)

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
        lambda steps: rng.random()
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
            noise = rng.uniform(low=-noise_fraction, high=noise_fraction, size=n)
        elif noise_type == "normal":
            noise = rng.normal(scale=noise_fraction, size=n)
        elif noise_type == "triangular":
            noise = rng.triangular(
                left=-noise_fraction, mode=0, right=noise_fraction, size=n
            )
        data[f"metric{j}"] = values + noise_fraction * values * noise
    return data


# Function to generate random text
def generate_random_text(length=10):
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def create_random_dataframe(rows=100, columns=5):
    rng = np.random.RandomState(seed=1337)

    data = rng.randint(0, 100, (rows, columns))
    df = pd.DataFrame(data)
    return df


def create_random_image(size=(100, 100)):
    rng = np.random.RandomState(seed=1337)

    array = rng.randint(0, 256, size + (3,), dtype=np.uint8)
    img = Image.fromarray(array)
    return wandb.Image(img)


def create_random_video():
    rng = np.random.RandomState(seed=1337)

    frames = rng.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
    return wandb.Video(frames, fps=4)


def create_random_audio():
    # Generate a random numpy array for audio data
    rng = np.random.RandomState(seed=1337)

    sampling_rate = 44100  # Typical audio sampling rate
    duration = 1.0  # duration in seconds
    audio_data = rng.uniform(low=-1.0, high=1.0, size=int(sampling_rate * duration))
    return wandb.Audio(audio_data, sample_rate=sampling_rate, caption="its audio yo")


def create_random_plotly():
    rng = np.random.RandomState(seed=1337)

    df = pd.DataFrame({"x": rng.rand(100), "y": rng.rand(100)})

    # Create a scatter plot
    fig = px.scatter(df, x="x", y="y")
    return fig


def create_random_html():
    fig = create_random_plotly()
    string = pio.to_html(fig)
    return wandb.Html(string)


def create_random_point_cloud():
    rng = np.random.RandomState(seed=1337)

    point_cloud = rng.rand(100, 3)
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

        artifact = wandb.Artifact(name, name)
        artifact.add_file(filename)

    return artifact
