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
from wandb import Api
import time

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

data = np.random.randint(255, size=(1000))


@pytest.fixture
def api(runner):
    return Api()


def test_wb_value(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    local_art = wandb.Artifact("N", "T")
    public_art = run.use_artifact("N:latest")

    wbvalue = data_types.WBValue()
    with pytest.raises(NotImplementedError):
        wbvalue.to_json(local_art)

    with pytest.raises(NotImplementedError):
        data_types.WBValue.from_json({}, public_art)

    assert data_types.WBValue.with_suffix("item") == "item.json"

    table = data_types.WBValue.init_from_json(
        {
            "_type": "table",
            "data": [[]],
            "columns": [],
            "column_types": wandb.data_types._dtypes.TypedDictType({}).to_json(),
        },
        public_art,
    )
    assert isinstance(table, data_types.WBValue) and isinstance(
        table, wandb.data_types.Table
    )

    type_mapping = data_types.WBValue.type_mapping()
    assert all(
        [issubclass(type_mapping[key], data_types.WBValue) for key in type_mapping]
    )

    assert wbvalue == wbvalue
    assert wbvalue != data_types.WBValue()


def test_log_dataframe(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    cv_results = pd.DataFrame(data={"test_col": [1, 2, 3], "test_col2": [4, 5, 6]})
    run.log({"results_df": cv_results})
    run.finish()
    ctx = live_mock_server.get_ctx()
    assert len(ctx["artifacts"]) == 1


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
        wandb.wandb_sdk.data_types._prune_max_seq(large_list), mocked_run, "test2", 0
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
        "size": 88244,
    }
    assert utils.subdict(meta["audio"][0], audio_expected) == audio_expected


def test_audio_refs():
    audioObj = wandb.Audio(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    art = wandb.Artifact("audio_ref_test", "dataset")
    art.add(audioObj, "audio_ref")

    audio_expected = {
        "_type": "audio-file",
        "caption": None,
    }
    assert utils.subdict(audioObj.to_json(art), audio_expected) == audio_expected


def test_guess_mode():
    image = np.random.randint(255, size=(28, 28, 3))
    wbimg = wandb.Image(image)
    assert wbimg.image.mode == "RGB"


def test_pil():
    pil = PIL.Image.new("L", (28, 28))
    img = wandb.Image(pil)
    assert list(img.image.getdata()) == list(pil.getdata())


def test_matplotlib_image():
    plt.plot([1, 2, 2, 4])
    img = wandb.Image(plt)
    assert img.image.width == 640


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


def test_molecule_file(runner, mocked_run):
    with runner.isolated_filesystem():
        with open("test.pdb", "w") as f:
            f.write("00000")
        mol = wandb.Molecule(open("test.pdb", "r"))
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


def test_html_file_path(mocked_run):
    with open("test.html", "w") as f:
        f.write("<html><body><h1>Hello</h1></body></html>")
    html = wandb.Html("test.html")
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


def test_table_eq_debug():
    # Invalid Type
    a = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    b = {}
    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b

    # Mismatch Rows
    a = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    b = wandb.Table(data=[[1, 2, 3]])
    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b

    # Mismatch Columns
    a = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    b = wandb.Table(data=[[1, 2, 3], [4, 5, 6]], columns=["a", "b", "c"])
    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b

    # Mismatch Types
    a = wandb.Table(data=[[1, 2, 3]])
    b = wandb.Table(data=[["1", "2", "3"]])
    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b

    # Mismatch Data
    a = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    b = wandb.Table(data=[[1, 2, 3], [4, 5, 100]])
    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b

    a = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    b = wandb.Table(data=[[1, 2, 3], [4, 5, 6]])
    a._eq_debug(b, True)
    assert a == b


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


def test_object3d_dict(mocked_run):
    obj = wandb.Object3D({"type": "lidar/beta",})
    obj.bind_to_run(mocked_run, "object3D", 0)
    assert obj.to_json(mocked_run)["_type"] == "object3D-file"


def test_object3d_dict_invalid(mocked_run):
    with pytest.raises(ValueError):
        obj = wandb.Object3D({"type": "INVALID",})


def test_object3d_dict_invalid_string(mocked_run):
    with pytest.raises(ValueError):
        obj = wandb.Object3D("INVALID")


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


def test_table_iterator():
    table = wandb.Table(data=table_data)
    for ndx, row in table.iterrows():
        assert row == table_data[ndx]

    table = wandb.Table(data=[])
    assert len([(ndx, row) for ndx, row in table.iterrows()]) == 0


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
    conv = data_types._numpy_arrays_to_lists
    assert conv(np.array((1, 2,))) == [1, 2]
    assert conv([np.array((1, 2,))]) == [[1, 2]]
    assert conv(np.array(({"a": [np.array((1, 2,))]}, 3))) == [{"a": [[1, 2]]}, 3]


def test_partitioned_table_from_json(runner, mock_server, api):
    # This is mocked to return some data
    art = api.artifact("entity/project/dummy:v0", type="dataset")
    ptable = art.get("dataset")
    data = [[0, 0, 1]]
    for ndx, row in ptable.iterrows():
        assert row == data[ndx]


def test_partitioned_table():
    partition_table = wandb.data_types.PartitionedTable(parts_path="parts")
    assert len([(ndx, row) for ndx, row in partition_table.iterrows()]) == 0
    assert partition_table == wandb.data_types.PartitionedTable(parts_path="parts")
    assert partition_table != wandb.data_types.PartitionedTable(parts_path="parts2")


def test_table_column_style():
    # Test Base Cases
    table1 = wandb.Table(columns=[], data=[])
    table1.add_column("number", [1, 2, 3])
    table1.add_data(4)
    with pytest.raises(AssertionError):
        table1.add_column("strings", ["a"])
    table1.add_column("strings", ["a", "b", "c", "d"])
    table1.set_pk("strings")
    table1.add_data(5, "e")
    table1.add_column("np_numbers", np.array([101, 102, 103, 104, 105]))

    assert table1.data == [
        [1, "a", 101],
        [2, "b", 102],
        [3, "c", 103],
        [4, "d", 104],
        [5, "e", 105],
    ]

    assert table1.get_column("number") == [1, 2, 3, 4, 5]
    assert table1.get_column("strings") == ["a", "b", "c", "d", "e"]
    assert table1.get_column("np_numbers") == [101, 102, 103, 104, 105]

    assert np.all(
        table1.get_column("number", convert_to="numpy") == np.array([1, 2, 3, 4, 5])
    )
    assert np.all(
        table1.get_column("strings", convert_to="numpy")
        == np.array(["a", "b", "c", "d", "e"])
    )
    assert np.all(
        table1.get_column("np_numbers", convert_to="numpy")
        == np.array([101, 102, 103, 104, 105])
    )

    ndxs = table1.get_index()
    assert ndxs == [0, 1, 2, 3, 4]
    assert [ndx._table == table1 for ndx in ndxs]

    # Test More Images and ndarrays
    rand_1 = np.random.randint(255, size=(32, 32))
    rand_2 = np.random.randint(255, size=(32, 32))
    rand_3 = np.random.randint(255, size=(32, 32))
    img_1 = wandb.Image(rand_1)
    img_2 = wandb.Image(rand_2)
    img_3 = wandb.Image(rand_3)

    table2 = wandb.Table(columns=[], data=[])
    table2.add_column("np_data", [rand_1, rand_2])
    table2.add_column("image", [img_1, img_2])
    table2.add_data(rand_3, img_3)

    assert table2.data == [[rand_1, img_1], [rand_2, img_2], [rand_3, img_3]]
    assert np.all(
        table2.get_column("np_data", convert_to="numpy")
        == np.array([rand_1, rand_2, rand_3])
    )
    assert table2.get_column("image") == [img_1, img_2, img_3]
    a = table2.get_column("image", convert_to="numpy")
    b = np.array([rand_1, rand_2, rand_3])
    assert np.all(
        table2.get_column("image", convert_to="numpy")
        == np.array([rand_1, rand_2, rand_3])
    )

    table3 = wandb.Table(columns=[], data=[])
    table3.add_column("table1_fk", table1.get_column("strings"))
    assert table3.get_column("table1_fk")[0]._table == table1


def test_ndarrays_in_tables():
    rows = 10
    d = 128
    c = 3
    nda_table = wandb.Table(
        columns=["ndarray"], data=np.random.randint(255, size=(rows, 1, d, d, c))
    )
    nda_table.add_data(np.random.randint(255, size=(d, d, c)))
    nda_table.add_data(np.random.randint(255, size=(d, d, c)).tolist())
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(d + 1, d, c)))
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(d + 1, d, c)).tolist())

    assert any(
        [
            isinstance(t, wandb.data_types._dtypes.NDArrayType)
            for t in nda_table._column_types.params["type_map"]["ndarray"].params[
                "allowed_types"
            ]
        ]
    )

    nda_table = wandb.Table(columns=[], data=[])
    nda_table.add_column(
        "odd_col",
        [[[i], [i]] for i in range(rows)] + [np.random.randint(255, size=(2, 1))],
    )

    assert isinstance(
        nda_table._column_types.params["type_map"]["odd_col"],
        wandb.data_types._dtypes.ListType,
    )

    nda_table.cast("odd_col", wandb.data_types._dtypes.NDArrayType(shape=(2, 1)))
    nda_table.add_data(np.random.randint(255, size=(2, 1)))
    nda_table.add_data(np.random.randint(255, size=(2, 1)).tolist())
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(2, 2)))
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(2, 2)).tolist())

    assert isinstance(
        nda_table._column_types.params["type_map"]["odd_col"],
        wandb.data_types._dtypes.NDArrayType,
    )


def test_table_logging(mocked_run, live_mock_server, test_settings, api):
    run = wandb.init(settings=test_settings)
    run.log(
        {
            "logged_table": wandb.Table(
                columns=["a"], data=[[wandb.Image(np.ones(shape=(32, 32)))]],
            )
        }
    )
    run.finish()
    assert True


def test_reference_table_logging(mocked_run, live_mock_server, test_settings, api):
    live_mock_server.set_ctx({"max_cli_version": "0.10.33"})
    run = wandb.init(settings=test_settings)
    t = wandb.Table(columns=["a"], data=[[wandb.Image(np.ones(shape=(32, 32)))]],)
    run.log({"logged_table": t})
    run.log({"logged_table": t})
    run.finish()
    assert True

    live_mock_server.set_ctx({"max_cli_version": "0.11.0"})
    run = wandb.init(settings=test_settings)
    t = wandb.Table(columns=["a"], data=[[wandb.Image(np.ones(shape=(32, 32)))]],)
    run.log({"logged_table": t})
    run.log({"logged_table": t})
    run.finish()
    assert True


def test_reference_table_artifacts(mocked_run, live_mock_server, test_settings, api):
    live_mock_server.set_ctx({"max_cli_version": "0.11.0"})
    run = wandb.init(settings=test_settings)
    t = wandb.Table(columns=["a"], data=[[wandb.Image(np.ones(shape=(32, 32)))]],)

    art = wandb.Artifact("A", "dataset")
    art.add(t, "table")
    run.log_artifact(art)
    art = wandb.Artifact("A", "dataset")
    art.add(t, "table")
    run.log_artifact(art)

    run.finish()
    assert True


# TODO: In another location: need to manually test the internal/backend
# artifact sender with an artifact that has a reference to be resolved - i
# think this will get the most coverage
def test_table_reference(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        run = wandb.init(settings=test_settings)
        artifact = run.use_artifact("dummy:v0")
        table = artifact.get("parts/1")
        run.log({"table": table})
        run.finish()
    assert True


def test_partitioned_table_logging(mocked_run, live_mock_server, test_settings, api):
    run = wandb.init(settings=test_settings)
    run.log({"logged_table": wandb.data_types.PartitionedTable("parts")})
    run.finish()
    assert True


def test_joined_table_logging(mocked_run, live_mock_server, test_settings, api):
    run = wandb.init(settings=test_settings)
    art = wandb.Artifact("A", "dataset")
    t1 = wandb.Table(
        columns=["id", "a"], data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
    )
    t2 = wandb.Table(
        columns=["id", "a"], data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
    )
    art.add(t1, "t1")
    art.add(t2, "t2")
    jt = wandb.JoinedTable(t1, t2, "id")
    art.add(jt, "jt")
    run.log_artifact(art)
    run.log({"logged_table": jt})
    run.finish()
    assert True
