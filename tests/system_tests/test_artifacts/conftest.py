import matplotlib.pyplot as plt
import numpy as np
import pytest
import wandb
from bokeh.plotting import figure
from rdkit import Chem
from wandb import data_types
from wandb.sdk.artifacts.artifact import Artifact


@pytest.fixture
def logged_artifact(wandb_init, user, example_files) -> Artifact:
    with wandb_init(entity=user, project="project") as run:
        artifact = wandb.Artifact("test-artifact", "dataset")
        artifact.add_dir(example_files)
        run.log_artifact(artifact)
    artifact.wait()
    return wandb.Api().artifact(f"{user}/project/test-artifact:v0")


@pytest.fixture
def linked_artifact(wandb_init, user, logged_artifact) -> Artifact:
    with wandb_init(entity=user, project="other-project") as run:
        run.link_artifact(logged_artifact, "linked-from-portfolio")

    return wandb.Api().artifact(f"{user}/other-project/linked-from-portfolio:v0")


@pytest.fixture
def audio_media() -> wandb.Audio:
    audio_data = np.random.uniform(-1, 1, 44100)
    return wandb.Audio(audio_data, sample_rate=44100)


@pytest.fixture
def video_media() -> wandb.Video:
    frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
    return wandb.Video(frames)


@pytest.fixture
def image_media() -> wandb.Image:
    return wandb.Image(np.ones(shape=(32, 32)))


@pytest.fixture
def table_media() -> wandb.Table:
    return wandb.Table(data=[[1]], columns=["A"])


@pytest.fixture
def graph_media() -> wandb.Graph:
    graph = wandb.Graph()
    node_a = data_types.Node("a", "Node A", size=(4,))
    node_b = data_types.Node("b", "Node B", size=(16,))
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(node_a, node_b)
    return graph


@pytest.fixture
def bokeh_media() -> data_types.Bokeh:
    x = [1, 2]
    y = [6, 7]
    p = figure(title="simple line example", x_axis_label="x", y_axis_label="y")
    p.line(x, y, legend_label="Temp.", line_width=2)
    return data_types.Bokeh(p)


@pytest.fixture
def html_media() -> wandb.Html:
    return wandb.Html("<html><body><h1>Hello, World!</h1></body></html>")


@pytest.fixture
def molecule_media() -> wandb.Molecule:
    m = Chem.MolFromSmiles("Cc1ccccc1")
    return wandb.Molecule.from_rdkit(m)


@pytest.fixture
def object3d_media() -> wandb.Object3D:
    point_cloud = np.random.rand(100, 3)
    return wandb.Object3D(point_cloud)


@pytest.fixture
def plotly_media() -> wandb.Plotly:
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    wandb.Plotly.make_plot_media(plt)
    return wandb.Plotly(fig)
