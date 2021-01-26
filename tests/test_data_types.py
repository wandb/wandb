import wandb
from wandb import data_types
import numpy as np
import pytest
import PIL
import os
import six
import sys
import glob
import platform
import pandas as pd
from click.testing import CliRunner
from . import utils
from .utils import dummy_data
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

data = np.random.randint(255, size=(1000))


def test_raw_data():
    wbhist = wandb.Histogram(data)
    assert len(wbhist.histogram) == 64


def test_np_histogram():
    wbhist = wandb.Histogram(np_histogram=np.histogram(data))
    assert len(wbhist.histogram) == 10


def test_manual_histogram():
    wbhist = wandb.Histogram(np_histogram=([1, 2, 4], [3, 10, 20, 0]))
    assert len(wbhist.histogram) == 3


def test_invalid_histogram():
    with pytest.raises(ValueError):
        wandb.Histogram(np_histogram=([1, 2, 3], [1]))


image = np.zeros((28, 28))


def test_captions():
    wbone = wandb.Image(image, caption="Cool")
    wbtwo = wandb.Image(image, caption="Nice")
    assert wandb.Image.all_captions([wbone, wbtwo]) == ["Cool", "Nice"]


def test_bind_image(mocked_run):
    wb_image = wandb.Image(image)
    wb_image.bind_to_run(mocked_run, "stuff", 10)
    assert wb_image.is_bound()


full_box = {
    "position": {"middle": (0.5, 0.5), "width": 0.1, "height": 0.2},
    "class_id": 2,
    "box_caption": "This is a big car",
    "scores": {"acc": 0.3},
}


# Helper function return a new dictionary with the key removed
def dissoc(d, key):
    new_d = d.copy()
    new_d.pop(key)
    return new_d


optional_keys = ["box_caption", "scores"]
boxes_with_removed_optional_args = [dissoc(full_box, k) for k in optional_keys]


def test_image_accepts_other_images(mocked_run):
    image_a = wandb.Image(np.random.random((300, 300, 3)))
    image_b = wandb.Image(image_a)
    assert image_a == image_b


def test_image_accepts_bounding_boxes(mocked_run):
    img = wandb.Image(image, boxes={"predictions": {"box_data": [full_box]}})
    img.bind_to_run(mocked_run, "images", 0)
    img_json = img.to_json(mocked_run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(mocked_run.dir, path))


def test_image_accepts_bounding_boxes_optional_args(mocked_run):
    img = data_types.Image(
        image, boxes={"predictions": {"box_data": boxes_with_removed_optional_args}}
    )
    img.bind_to_run(mocked_run, "images", 0)
    img_json = img.to_json(mocked_run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(mocked_run.dir, path))


standard_mask = {
    "mask_data": np.array([[1, 2, 2, 2], [2, 3, 3, 4], [4, 4, 4, 4], [4, 4, 4, 2]]),
    "class_labels": {1: "car", 2: "pedestrian", 3: "tractor", 4: "cthululu"},
}


def test_image_accepts_masks(mocked_run):
    img = wandb.Image(image, masks={"overlay": standard_mask})
    img.bind_to_run(mocked_run, "images", 0)
    img_json = img.to_json(mocked_run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(mocked_run.dir, path))


def test_image_accepts_masks_without_class_labels(mocked_run):
    img = wandb.Image(image, masks={"overlay": dissoc(standard_mask, "class_labels")})
    img.bind_to_run(mocked_run, "images", 0)
    img_json = img.to_json(mocked_run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(mocked_run.dir, path))


def test_cant_serialize_to_other_run(mocked_run, test_settings):
    """This isn't implemented yet. Should work eventually.
    """
    other_run = wandb.wandb_sdk.wandb_run.Run(settings=test_settings)
    other_run._set_backend(mocked_run._backend)
    wb_image = wandb.Image(image)

    wb_image.bind_to_run(mocked_run, "stuff", 10)

    with pytest.raises(AssertionError):
        wb_image.to_json(other_run)


def test_image_seq_to_json(mocked_run):
    wb_image = wandb.Image(image)
    wb_image.bind_to_run(mocked_run, "test", 0, 0)
    meta = wandb.Image.seq_to_json([wb_image], mocked_run, "test", 0)
    assert os.path.exists(
        os.path.join(mocked_run.dir, "media", "images", "test_0_0.png")
    )

    meta_expected = {
        "_type": "images/separated",
        "count": 1,
        "height": 28,
        "width": 28,
    }
    assert utils.subdict(meta, meta_expected) == meta_expected


def test_max_images(caplog, mocked_run):
    large_image = np.random.randint(255, size=(10, 10))
    large_list = [wandb.Image(large_image)] * 200
    large_list[0].bind_to_run(mocked_run, "test2", 0, 0)
    meta = wandb.Image.seq_to_json(
        data_types.prune_max_seq(large_list), mocked_run, "test2", 0
    )
    expected = {
        "_type": "images/separated",
        "count": data_types.Image.MAX_ITEMS,
        "height": 10,
        "width": 10,
    }
    path = os.path.join(mocked_run.dir, "media/images/test2_0_0.png")
    assert utils.subdict(meta, expected) == expected
    assert os.path.exists(os.path.join(mocked_run.dir, "media/images/test2_0_0.png"))


def test_audio_sample_rates():
    audio1 = np.random.uniform(-1, 1, 44100)
    audio2 = np.random.uniform(-1, 1, 88200)
    wbaudio1 = wandb.Audio(audio1, sample_rate=44100)
    wbaudio2 = wandb.Audio(audio2, sample_rate=88200)
    assert wandb.Audio.sample_rates([wbaudio1, wbaudio2]) == [44100, 88200]
    # test with missing sample rate
    with pytest.raises(ValueError):
        wandb.Audio(audio1)


def test_audio_durations():
    audio1 = np.random.uniform(-1, 1, 44100)
    audio2 = np.random.uniform(-1, 1, 88200)
    wbaudio1 = wandb.Audio(audio1, sample_rate=44100)
    wbaudio2 = wandb.Audio(audio2, sample_rate=44100)
    assert wandb.Audio.durations([wbaudio1, wbaudio2]) == [1.0, 2.0]


def test_audio_captions():
    audio = np.random.uniform(-1, 1, 44100)
    sample_rate = 44100
    caption1 = "This is what a dog sounds like"
    caption2 = "This is what a chicken sounds like"
    # test with all captions
    wbaudio1 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption1)
    wbaudio2 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption2)
    assert wandb.Audio.captions([wbaudio1, wbaudio2]) == [caption1, caption2]
    # test with no captions
    wbaudio3 = wandb.Audio(audio, sample_rate=sample_rate)
    wbaudio4 = wandb.Audio(audio, sample_rate=sample_rate)
    assert wandb.Audio.captions([wbaudio3, wbaudio4]) is False
    # test with some captions
    wbaudio5 = wandb.Audio(audio, sample_rate=sample_rate)
    wbaudio6 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption2)
    assert wandb.Audio.captions([wbaudio5, wbaudio6]) == ["", caption2]


def test_audio_to_json(mocked_run):
    audio = np.zeros(44100)
    audioObj = wandb.Audio(audio, sample_rate=44100)
    audioObj.bind_to_run(mocked_run, "test", 0)
    meta = wandb.Audio.seq_to_json([audioObj], mocked_run, "test", 0)
    assert os.path.exists(os.path.join(mocked_run.dir, meta["audio"][0]["path"]))

    meta_expected = {
        "_type": "audio",
        "count": 1,
        "sampleRates": [44100],
        "durations": [1.0],
    }
    assert utils.subdict(meta, meta_expected) == meta_expected

    audio_expected = {
        "_type": "audio-file",
        "caption": None,
        "sample_rate": 44100,
        "size": 88244,
    }
    assert utils.subdict(meta["audio"][0], audio_expected) == audio_expected


def test_guess_mode():
    image = np.random.randint(255, size=(28, 28, 3))
    wbimg = wandb.Image(image)
    assert wbimg._image.mode == "RGB"


def test_pil():
    pil = PIL.Image.new("L", (28, 28))
    img = wandb.Image(pil)
    assert img._image == pil


def test_matplotlib_image():
    plt.plot([1, 2, 2, 4])
    img = wandb.Image(plt)
    assert img._image.width == 640


def test_matplotlib_image_with_multiple_axes():
    """Ensures that wandb.Image constructor can accept a pyplot or figure 
    reference in which the figure has multiple axes. Importantly, there is 
    no requirement that any of the axes have plotted data.
    """
    for fig in utils.matplotlib_multiple_axes_figures():
        wandb.Image(fig)  # this should not error.

    for fig in utils.matplotlib_multiple_axes_figures():
        wandb.Image(plt)  # this should not error.


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="plotly doesn't support py3.9 yet"
)
def test_matplotlib_plotly_with_multiple_axes():
    """Ensures that wandb.Plotly constructor can accept a plotly figure 
    reference in which the figure has multiple axes. Importantly, there is 
    no requirement that any of the axes have plotted data.
    """
    for fig in utils.matplotlib_multiple_axes_figures():
        wandb.Plotly(fig)  # this should not error.

    for fig in utils.matplotlib_multiple_axes_figures():
        wandb.Plotly(plt)  # this should not error.


def test_plotly_from_matplotlib_with_image():
    """Ensures that wandb.Plotly constructor properly errors when
    a pyplot with image is passed 
    """
    # try the figure version
    fig = utils.matplotlib_with_image()
    with pytest.raises(ValueError):
        wandb.Plotly(fig)
    plt.close()

    # try the plt version
    fig = utils.matplotlib_with_image()
    with pytest.raises(ValueError):
        wandb.Plotly(plt)
    plt.close()


def test_image_from_matplotlib_with_image():
    """Ensures that wandb.Image constructor supports a pyplot with image is passed 
    """
    # try the figure version
    fig = utils.matplotlib_with_image()
    wandb.Image(fig)  # this should not error.
    plt.close()

    # try the plt version
    fig = utils.matplotlib_with_image()
    wandb.Image(plt)  # this should not error.
    plt.close()


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="plotly doesn't support py3.9 yet"
)
def test_make_plot_media_from_matplotlib_without_image():
    """Ensures that wand.Plotly.make_plot_media() returns a Plotly object when
    there is no image
    """
    fig = utils.matplotlib_without_image()
    assert type(wandb.Plotly.make_plot_media(fig)) == wandb.Plotly
    plt.close()

    fig = utils.matplotlib_without_image()
    assert type(wandb.Plotly.make_plot_media(plt)) == wandb.Plotly
    plt.close()


def test_make_plot_media_from_matplotlib_with_image():
    """Ensures that wand.Plotly.make_plot_media() returns an Image object when
    there is an image in the matplotlib figure
    """
    fig = utils.matplotlib_with_image()
    assert type(wandb.Plotly.make_plot_media(fig)) == wandb.Image
    plt.close()

    fig = utils.matplotlib_with_image()
    assert type(wandb.Plotly.make_plot_media(plt)) == wandb.Image
    plt.close()


def test_create_bokeh_plot(mocked_run):
    """Ensures that wandb.Bokeh constructor accepts a bokeh plot 
    """
    bp = dummy_data.bokeh_plot()
    bp = wandb.data_types.Bokeh(bp)
    bp.bind_to_run(mocked_run, "bokeh", 0)


@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_gif(mocked_run):
    video = np.random.randint(255, size=(10, 3, 28, 28))
    vid = wandb.Video(video, format="gif")
    vid.bind_to_run(mocked_run, "videos", 0)
    assert vid.to_json(mocked_run)["path"].endswith(".gif")


@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_mp4(mocked_run):
    video = np.random.randint(255, size=(10, 3, 28, 28))
    vid = wandb.Video(video, format="mp4")
    vid.bind_to_run(mocked_run, "videos", 0)
    assert vid.to_json(mocked_run)["path"].endswith(".mp4")


@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_multi(mocked_run):
    video = np.random.random(size=(2, 10, 3, 28, 28))
    vid = wandb.Video(video)
    vid.bind_to_run(mocked_run, "videos", 0)
    assert vid.to_json(mocked_run)["path"].endswith(".gif")


@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_invalid():
    video = np.random.random(size=(3, 28, 28))
    with pytest.raises(ValueError):
        wandb.Video(video)


def test_video_path(mocked_run):
    with open("video.mp4", "w") as f:
        f.write("00000")
    vid = wandb.Video("video.mp4")
    vid.bind_to_run(mocked_run, "videos", 0)
    assert vid.to_json(mocked_run)["path"].endswith(".mp4")


def test_video_path_invalid(runner):
    with runner.isolated_filesystem():
        with open("video.avi", "w") as f:
            f.write("00000")
        with pytest.raises(ValueError):
            wandb.Video("video.avi")


def test_molecule(runner, mocked_run):
    with runner.isolated_filesystem():
        with open("test.pdb", "w") as f:
            f.write("00000")
        mol = wandb.Molecule("test.pdb")
        mol.bind_to_run(mocked_run, "rad", "summary")
        wandb.Molecule.seq_to_json([mol], mocked_run, "rad", "summary")

        assert os.path.exists(mol._path)


def test_html_str(mocked_run):
    html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
    html.bind_to_run(mocked_run, "rad", "summary")
    wandb.Html.seq_to_json([html], mocked_run, "rad", "summary")
    assert os.path.exists(html._path)


def test_html_styles():
    with CliRunner().isolated_filesystem():
        pre = (
            '<base target="_blank"><link rel="stylesheet" type="text/css" '
            'href="https://app.wandb.ai/normalize.css" />'
        )
        html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
        assert (
            html.html
            == "<html><head>" + pre + "</head><body><h1>Hello</h1></body></html>"
        )
        html = wandb.Html("<html><head></head><body><h1>Hello</h1></body></html>")
        assert (
            html.html
            == "<html><head>" + pre + "</head><body><h1>Hello</h1></body></html>"
        )
        html = wandb.Html("<h1>Hello</h1>")
        assert html.html == pre + "<h1>Hello</h1>"
        html = wandb.Html("<h1>Hello</h1>", inject=False)
        assert html.html == "<h1>Hello</h1>"


def test_html_file(mocked_run):
    with open("test.html", "w") as f:
        f.write("<html><body><h1>Hello</h1></body></html>")
    html = wandb.Html(open("test.html"))
    html.bind_to_run(mocked_run, "rad", "summary")
    wandb.Html.seq_to_json([html, html], mocked_run, "rad", "summary")

    assert os.path.exists(html._path)


def test_table_default():
    table = wandb.Table()
    table.add_data("Some awesome text", "Positive", "Negative")
    assert table._to_table_json() == {
        "data": [["Some awesome text", "Positive", "Negative"]],
        "columns": ["Input", "Output", "Expected"],
    }


def test_table_custom():
    table = wandb.Table(["Foo", "Bar"])
    table.add_data("So", "Cool")
    table.add_row("&", "Rad")
    assert table._to_table_json() == {
        "data": [["So", "Cool"], ["&", "Rad"]],
        "columns": ["Foo", "Bar"],
    }
    df = pd.DataFrame(columns=["Foo", "Bar"], data=[["So", "Cool"], ["&", "Rad"]])
    table_df = wandb.Table(dataframe=df)
    assert table._to_table_json() == table_df._to_table_json()


point_cloud_1 = np.array([[0, 0, 0, 1], [0, 0, 1, 13], [0, 1, 0, 2], [0, 1, 0, 4]])

point_cloud_2 = np.array([[0, 0, 0], [0, 0, 1], [0, 1, 0], [0, 1, 0]])

point_cloud_3 = np.array(
    [
        [0, 0, 0, 100, 100, 100],
        [0, 0, 1, 100, 100, 100],
        [0, 1, 0, 100, 100, 100],
        [0, 1, 0, 100, 100, 100],
    ]
)


def test_object3d_numpy(mocked_run):
    obj1 = wandb.Object3D(point_cloud_1)
    obj2 = wandb.Object3D(point_cloud_2)
    obj3 = wandb.Object3D(point_cloud_3)
    obj1.bind_to_run(mocked_run, "object3d", 0)
    obj2.bind_to_run(mocked_run, "object3d", 1)
    obj3.bind_to_run(mocked_run, "object3d", 2)
    assert obj1.to_json(mocked_run)["_type"] == "object3D-file"
    assert obj2.to_json(mocked_run)["_type"] == "object3D-file"
    assert obj3.to_json(mocked_run)["_type"] == "object3D-file"


def test_object3d_obj(mocked_run):
    obj = wandb.Object3D(utils.fixture_open("cube.obj"))
    obj.bind_to_run(mocked_run, "object3D", 0)
    assert obj.to_json(mocked_run)["_type"] == "object3D-file"


def test_object3d_gltf(mocked_run):
    obj = wandb.Object3D(utils.fixture_open("Box.gltf"))
    obj.bind_to_run(mocked_run, "object3D", 0)
    assert obj.to_json(mocked_run)["_type"] == "object3D-file"


def test_object3d_io(mocked_run):
    f = utils.fixture_open("Box.gltf")
    body = f.read()

    ioObj = six.StringIO(six.u(body))
    obj = wandb.Object3D(ioObj, file_type="obj")
    obj.bind_to_run(mocked_run, "object3D", 0)
    assert obj.to_json(mocked_run)["_type"] == "object3D-file"


def test_object3d_unsupported_numpy():
    with pytest.raises(ValueError):
        wandb.Object3D(np.array([1]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([[1, 2], [3, 4], [1, 2]]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([1, 3, 4, 5, 6, 7, 8, 8, 3]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([[1, 3, 4, 5, 6, 7, 8, 8, 3]]))

    f = utils.fixture_open("Box.gltf")
    body = f.read()
    ioObj = six.StringIO(six.u(body))

    with pytest.raises(ValueError):
        wandb.Object3D(ioObj)


def test_object3d_seq_to_json(mocked_run):
    objs = [
        wandb.Object3D(utils.fixture_open("Box.gltf")),
        wandb.Object3D(utils.fixture_open("cube.obj")),
        wandb.Object3D(point_cloud_1),
    ]
    for o in objs:
        o.bind_to_run(mocked_run, "pc", 1)

    obj = wandb.Object3D.seq_to_json(objs, mocked_run, "pc", 1)

    box = obj["filenames"][0]
    cube = obj["filenames"][1]
    pts = obj["filenames"][2]

    assert os.path.exists(os.path.join(mocked_run.dir, "media", "object3D", box))
    assert os.path.exists(os.path.join(mocked_run.dir, "media", "object3D", cube))
    assert os.path.exists(os.path.join(mocked_run.dir, "media", "object3D", pts))

    assert obj["_type"] == "object3D"
    assert obj["filenames"] == [
        box,
        cube,
        pts,
    ]


def test_table_init():
    table = wandb.Table(data=[["Some awesome text", "Positive", "Negative"]])
    assert table._to_table_json() == {
        "data": [["Some awesome text", "Positive", "Negative"]],
        "columns": ["Input", "Output", "Expected"],
    }


table_data = [
    ["a", 1, True],
    ["b", 2, False],
    ["c", 3, True],
]


def test_table_from_list():
    table = wandb.Table(data=table_data)
    assert table.data == table_data

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(table_data)

    with pytest.raises(AssertionError):
        # raises when user uses list in "dataframe"
        table = wandb.Table(dataframe=table_data)

    # legacy
    table = wandb.Table(rows=table_data)
    assert table.data == table_data


def test_table_from_numpy():
    np_data = np.array(table_data)
    table = wandb.Table(data=np_data)
    assert table.data == np_data.tolist()

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(np_data)

    with pytest.raises(AssertionError):
        # raises when user uses list in "dataframe"
        table = wandb.Table(dataframe=np_data)


def test_table_from_pandas():
    pd_data = pd.DataFrame(table_data)
    table = wandb.Table(data=pd_data)
    assert table.data == table_data

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(pd_data)

    # legacy
    table = wandb.Table(dataframe=pd_data)
    assert table.data == table_data


def test_graph():
    graph = wandb.Graph()
    node_a = data_types.Node("a", "Node A", size=(4,))
    node_b = data_types.Node("b", "Node B", size=(16,))
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(node_a, node_b)
    assert graph._to_graph_json() == {
        "edges": [["a", "b"]],
        "format": "keras",
        "nodes": [
            {"id": "a", "name": "Node A", "size": (4,)},
            {"id": "b", "name": "Node B", "size": (16,)},
        ],
    }


def test_numpy_arrays_to_list():
    conv = data_types.numpy_arrays_to_lists
    assert conv(np.array((1, 2,))) == [1, 2]
    assert conv([np.array((1, 2,))]) == [[1, 2]]
    assert conv(np.array(({"a": [np.array((1, 2,))]}, 3))) == [{"a": [[1, 2]]}, 3]
