import wandb
from wandb import data_types
import numpy as np
import pytest
import PIL
import os
import matplotlib
import six
import sys

matplotlib.use("Agg")
from click.testing import CliRunner
import matplotlib.pyplot as plt
from click.testing import CliRunner

from . import utils

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
        wbhist = wandb.Histogram(np_histogram=([1, 2, 3], [1]))


def test_histogram_to_json():
    wbhist = wandb.Histogram(data)
    json = wbhist.to_json()
    assert json["_type"] == "histogram"
    assert len(json["values"]) == 64


image = np.zeros((28, 28))


def test_captions():
    wbone = wandb.Image(image, caption="Cool")
    wbtwo = wandb.Image(image, caption="Nice")
    assert wandb.Image.captions([wbone, wbtwo]) == ["Cool", "Nice"]


def test_bind_image():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        wb_image = wandb.Image(image)
        wb_image.bind_to_run(run, 'stuff', 10)
        assert wb_image.is_bound()

        with pytest.raises(RuntimeError):
            wb_image.bind_to_run(run, 'stuff', 10)


def test_cant_serialize_to_other_run():
    """This isn't implemented yet. Should work eventually.
    """
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        other_run = wandb.wandb_run.Run()
        wb_image = wandb.Image(image)

        wb_image.bind_to_run(run, 'stuff', 10)

        with pytest.raises(AssertionError):
            wb_image.to_json(other_run)


def test_image_seq_to_json():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        wb_image = wandb.Image(image)
        meta = wandb.Image.seq_to_json([wb_image], run, "test", 'summary')
        assert os.path.exists(os.path.join(run.dir, 'media', 'images', 'test_summary.png'))

        meta_expected = {
            '_type': 'images',
            'count': 1,
            'height': 28,
            'width': 28,
        }
        assert utils.subdict(meta, meta_expected) == meta_expected

def test_transform_caps_at_65500(caplog):
    large_image = np.random.randint(255, size=(10, 1000))
    large_list = [wandb.Image(large_image)] * 100
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        meta = wandb.Image.seq_to_json(large_list, run, "test2", 0)
        expected = {'_type': 'images', 'count': 65, 'height': 10, 'width': 1000}
        assert utils.subdict(meta, expected) == expected
        assert os.path.exists(os.path.join(run.dir, "media/images/test2_0.png"))
        assert 'Only 65 images will be uploaded. The maximum total width for a set of thumbnails is 65,500px, or 65 images, each with a width of 1000 pixels.' in caplog.text

def test_audio_sample_rates():
    audio1 = np.random.uniform(-1, 1, 44100)
    audio2 = np.random.uniform(-1, 1, 88200)
    wbaudio1 = wandb.Audio(audio1, sample_rate=44100)
    wbaudio2 = wandb.Audio(audio2, sample_rate=88200)
    assert wandb.Audio.sample_rates([wbaudio1, wbaudio2]) == [44100, 88200]
    # test with missing sample rate
    with pytest.raises(ValueError):
        wbaudio3 = wandb.Audio(audio1)


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
    assert wandb.Audio.captions([wbaudio3, wbaudio4]) == False
    # test with some captions
    wbaudio5 = wandb.Audio(audio, sample_rate=sample_rate)
    wbaudio6 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption2)
    assert wandb.Audio.captions([wbaudio5, wbaudio6]) == ['', caption2]


def test_audio_to_json():
    audio = np.zeros(44100)
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        meta = wandb.Audio.seq_to_json(
            [wandb.Audio(audio, sample_rate=44100)], run, "test", 0)
        assert os.path.exists(os.path.join(run.dir, meta['audio'][0]['path']))

        meta_expected = {
            '_type': 'audio',
            'count': 1,
            'sampleRates': [44100],
            'durations': [1.0],
        }
        assert utils.subdict(meta, meta_expected) == meta_expected

        audio_expected = {
            '_type': 'audio-file',
            'caption': None,
            'sample_rate': 44100,
            'size': 88244,
        }
        assert utils.subdict(meta['audio'][0], audio_expected) == audio_expected


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

@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        video = np.random.randint(255, size=(10,3,28,28))
        vid = wandb.Video(video)
        vid.bind_to_run(run, "videos", 0)
        assert vid.to_json(run)["path"].endswith(".gif")

@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_multi():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        video = np.random.random(size=(2,10,3,28,28))
        vid = wandb.Video(video)
        vid.bind_to_run(run, "videos", 0)
        assert vid.to_json(run)["path"].endswith(".gif")

@pytest.mark.skipif(sys.version_info < (3, 6), reason="No moviepy.editor in py2")
def test_video_numpy_invalid():
    run = wandb.wandb_run.Run()
    video = np.random.random(size=(3,28,28))
    with pytest.raises(ValueError):
        vid = wandb.Video(video)

def test_video_path():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        with open("video.mp4", "w") as f:
            f.write("00000")
        vid = wandb.Video("video.mp4")
        vid.bind_to_run(run, "videos", 0)
        assert vid.to_json(run)["path"].endswith(".mp4")

def test_video_path_invalid():
    run = wandb.wandb_run.Run()
    with CliRunner().isolated_filesystem():
        with open("video.avi", "w") as f:
            f.write("00000")
        with pytest.raises(ValueError):
            vid = wandb.Video("video.avi")

def test_html_str():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
        wandb.Html.seq_to_json([html], run, "rad", "summary")
        assert os.path.exists(os.path.join(run.dir, "media/html/rad_summary_0.html"))


def test_html_styles():
    with CliRunner().isolated_filesystem():
        pre = '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />'
        html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
        assert html.html == "<html><head>"+pre + \
            "</head><body><h1>Hello</h1></body></html>"
        html = wandb.Html(
            "<html><head></head><body><h1>Hello</h1></body></html>")
        assert html.html == "<html><head>"+pre + \
            "</head><body><h1>Hello</h1></body></html>"
        html = wandb.Html("<h1>Hello</h1>")
        assert html.html == pre + "<h1>Hello</h1>"
        html = wandb.Html("<h1>Hello</h1>", inject=False)
        assert html.html == "<h1>Hello</h1>"


def test_html_file():
    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()
        with open("test.html", "w") as f:
            f.write("<html><body><h1>Hello</h1></body></html>")
        html = wandb.Html(open("test.html"))
        wandb.Html.seq_to_json([html, html], run, "rad", "summary")
        assert os.path.exists(os.path.join(run.dir, "media/html/rad_summary_0.html"))
        assert os.path.exists(os.path.join(run.dir, "media/html/rad_summary_0.html"))


def test_table_default():
    table = wandb.Table()
    table.add_data("Some awesome text", "Positive", "Negative")
    assert table._to_table_json() == {
        "data": [["Some awesome text", "Positive", "Negative"]],
        "columns": ["Input", "Output", "Expected"]
    }


def test_table_custom():
    table = wandb.Table(["Foo", "Bar"])
    table.add_data("So", "Cool")
    table.add_row("&", "Rad")
    assert table._to_table_json() == {
        "data": [["So", "Cool"], ["&", "Rad"]],
        "columns": ["Foo", "Bar"]
    }


point_cloud_1 = np.array([[0, 0, 0, 1],
                          [0, 0, 1, 13],
                          [0, 1, 0, 2],
                          [0, 1, 0, 4]])

point_cloud_2 = np.array([[0, 0, 0],
                          [0, 0, 1],
                          [0, 1, 0],
                          [0, 1, 0]])

point_cloud_3 = np.array([[0, 0, 0, 100, 100, 100],
                          [0, 0, 1, 100, 100, 100],
                          [0, 1, 0, 100, 100, 100],
                          [0, 1, 0, 100, 100, 100]])


def test_object3d_numpy():
    obj = wandb.Object3D(point_cloud_1)
    obj = wandb.Object3D(point_cloud_2)
    obj = wandb.Object3D(point_cloud_3)


def test_object3d_obj():
    obj = wandb.Object3D(open("tests/fixtures/cube.obj"))


def test_object3d_gltf():
    obj = wandb.Object3D(open("tests/fixtures/Box.gltf"))


def test_object3d_io():
    f = open("tests/fixtures/Box.gltf")
    body = f.read()

    ioObj = six.StringIO(six.u(body))
    obj = wandb.Object3D(ioObj, file_type="obj")


def test_object3d_unsupported_numpy():
    with pytest.raises(ValueError):
        wandb.Object3D(np.array([1]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([[1, 2], [3, 4], [1, 2]]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([1, 3, 4, 5, 6, 7, 8, 8, 3]))

    with pytest.raises(ValueError):
        wandb.Object3D(np.array([[1, 3, 4, 5, 6, 7, 8, 8, 3]]))

    f = open("tests/fixtures/Box.gltf")
    body = f.read()
    ioObj = six.StringIO(six.u(body))

    with pytest.raises(ValueError):
        obj = wandb.Object3D(ioObj)


def test_object3d_seq_to_json():
    cwd = os.getcwd()

    with CliRunner().isolated_filesystem():
        run = wandb.wandb_run.Run()

        obj = wandb.Object3D.seq_to_json([
            wandb.Object3D(open(os.path.join(cwd, "tests/fixtures/Box.gltf"))),
            wandb.Object3D(open(os.path.join(cwd, "tests/fixtures/cube.obj"))),
            wandb.Object3D(point_cloud_1)
        ], run, "pc", 1)

        print(obj)


        assert os.path.exists(os.path.join(run.dir, "media/object3D/Box_be115756.gltf"))
        assert os.path.exists(os.path.join(run.dir, "media/object3D/cube_afff12bc.obj"))
        assert os.path.exists(os.path.join(run.dir, 
            "media/object3D/pc_1_2.pts.json"))

        assert obj["_type"] == "object3D"
        assert obj["filenames"] == [
            "Box_be115756.gltf",
            "cube_afff12bc.obj",
            "pc_1_2.pts.json",
        ]


def test_table_init():
    table = wandb.Table(data=[["Some awesome text", "Positive", "Negative"]])
    assert table._to_table_json() == {
        "data": [["Some awesome text", "Positive", "Negative"]],
        "columns": ["Input", "Output", "Expected"]}

def test_graph():
    graph = wandb.Graph()
    node_a = data_types.Node('a', 'Node A', size=(4,))
    node_b = data_types.Node('b', 'Node B', size=(16,))
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(node_a, node_b)
    assert graph._to_graph_json() == {
        'edges': [['a', 'b']],
        'format': 'keras',
        'nodes': [{'id': 'a', 'name': 'Node A', 'size': (4,)},
                  {'id': 'b', 'name': 'Node B', 'size': (16,)}]}

def test_numpy_arrays_to_list():
    conv = data_types.numpy_arrays_to_lists
    assert conv(np.array((1,2,))) == [1, 2]
    assert conv([np.array((1,2,))]) == [[1, 2]]
    assert conv(np.array(({'a': [np.array((1,2,))]}, 3))) == [{'a': [[1, 2]]}, 3]