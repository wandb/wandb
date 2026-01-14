import os
import platform
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest
import wandb
from bokeh.plotting import figure
from rdkit import Chem
from wandb import data_types

data = np.random.randint(255, size=(1000))


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


@pytest.mark.parametrize(
    "media_object",
    [
        "table_media",
        "image_media",
        "video_media",
        "audio_media",
        "graph_media",
        "bokeh_media",
        "html_media",
        "molecule_media",
        "object3d_media",
        "plotly_media",
    ],
)
def test_log_media_saves_to_run_directory(mock_run, request, media_object):
    run = mock_run(use_magic_mock=True)
    media_object = request.getfixturevalue(media_object)

    media_object.bind_to_run(run, "/media/path", 0)

    # Assert media object is saved under the run directory
    assert media_object._path.startswith(run.dir)


@pytest.mark.parametrize(
    "invalid_character",
    [
        "<",
        ">",
        ":",
        "\\",
        "?",
        "*",
    ],
)
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
def test_log_media_with_invalid_character_on_windows(
    mock_run, image_media, invalid_character
):
    run = mock_run()
    with pytest.raises(ValueError, match="Path .* is invalid"):
        image_media.bind_to_run(run, f"image{invalid_character}test", 0)


def test_log_media_with_path_traversal(mock_run, image_media):
    run = mock_run()
    image_media.bind_to_run(run, "../../../image", 0)

    # Resolve to path to verify no path traversals
    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)
    assert os.path.exists(resolved_path)


@pytest.mark.parametrize(
    "media_key",
    [
        "////image",
        "my///image",
    ],
)
def test_log_media_prefixed_with_multiple_slashes(mock_run, media_key, image_media):
    run = mock_run()
    image_media.bind_to_run(run, media_key, 0)

    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)
    assert os.path.exists(resolved_path)
