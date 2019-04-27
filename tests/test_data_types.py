import wandb
import numpy as np
import pytest
import PIL
import os
import matplotlib
import six

matplotlib.use("Agg")
from click.testing import CliRunner
import matplotlib.pyplot as plt
import soundfile

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


def test_fucked_up_histogram():
    with pytest.raises(ValueError):
        wbhist = wandb.Histogram(np_histogram=([1, 2, 3], [1]))


def test_transform():
    wbhist = wandb.Histogram(data)
    json = wandb.Histogram.transform(wbhist)
    assert json["_type"] == "histogram"
    assert len(json["values"]) == 64


image = np.random.randint(255, size=(28, 28))


def test_captions():
    wbone = wandb.Image(image, caption="Cool")
    wbtwo = wandb.Image(image, caption="Nice")
    assert wandb.Image.captions([wbone, wbtwo]) == ["Cool", "Nice"]


def test_transform():
    with CliRunner().isolated_filesystem():
        meta = wandb.Image.transform([wandb.Image(image)], ".", "test.jpg")
        assert meta == {'_type': 'images',
                        'count': 1, 'height': 28, 'width': 28}
        assert os.path.exists("media/images/test.jpg")

def test_transform_caps_at_65500(caplog):
    large_image = np.random.randint(255, size=(10, 1000))
    large_list = [wandb.Image(large_image)] * 100
    with CliRunner().isolated_filesystem():
        meta = wandb.Image.transform(large_list, ".", "test2.jpg")
        assert meta == {'_type': 'images',
                        'count': 65, 'height': 10, 'width': 1000}
        assert os.path.exists("media/images/test2.jpg")
        assert 'The maximum total width for all images in a collection is 65500, or 65 images, each with a width of 1000 pixels. Only logging the first 65 images.' in caplog.text

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


def test_audio_transform():
    audio = np.random.uniform(-1, 1, 44100)
    with CliRunner().isolated_filesystem():
        meta = wandb.Audio.transform(
            [wandb.Audio(audio, sample_rate=44100)], ".", "test", 0)
        assert meta == {'_type': 'audio',
                        'count': 1, 'sampleRates': [44100], 'durations': [1.0]}
        assert os.path.exists("media/audio/test_0_0.wav")


def test_guess_mode():
    image = np.random.randint(255, size=(28, 28, 3))
    wbimg = wandb.Image(image)
    assert wbimg.image.mode == "RGB"


def test_pil():
    pil = PIL.Image.new("L", (28, 28))
    img = wandb.Image(pil)
    assert img.image == pil


def test_matplotlib_image():
    plt.plot([1, 2, 2, 4])
    img = wandb.Image(plt)
    assert img.image.width == 640


def test_html_str():
    with CliRunner().isolated_filesystem():
        html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
        wandb.Html.transform([html], ".", "rad", "summary")
        assert os.path.exists("media/html/rad_summary_0.html")


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
        with open("test.html", "w") as f:
            f.write("<html><body><h1>Hello</h1></body></html>")
        html = wandb.Html(open("test.html"))
        wandb.Html.transform([html, html], ".", "rad", "summary")
        assert os.path.exists("media/html/rad_summary_0.html")
        assert os.path.exists("media/html/rad_summary_1.html")


def test_table_default():
    table = wandb.Table()
    table.add_data("Some awesome text", "Positive", "Negative")
    assert wandb.Table.transform(table) == {"_type": "table",
                                            "data": [["Some awesome text", "Positive", "Negative"]],
                                            "columns": ["Input", "Output", "Expected"]}


def test_table_custom():
    table = wandb.Table(["Foo", "Bar"])
    table.add_data("So", "Cool")
    table.add_row("&", "Rad")
    assert wandb.Table.transform(table) == {"_type": "table",
                                            "data": [["So", "Cool"], ["&", "Rad"]],
                                            "columns": ["Foo", "Bar"]}


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
    np.testing.assert_array_equal(obj.numpyData, point_cloud_1)

    obj = wandb.Object3D(point_cloud_2)
    np.testing.assert_array_equal(obj.numpyData, point_cloud_2)

    obj = wandb.Object3D(point_cloud_3)
    np.testing.assert_array_equal(obj.numpyData, point_cloud_3)


def test_object3d_obj():
    obj = wandb.Object3D(open("tests/fixtures/cube.obj"))
    assert obj.extension == "obj"


def test_object3d_gltf():
    obj = wandb.Object3D(open("tests/fixtures/Box.gltf"))
    assert obj.extension == "gltf"


def test_object3d_io():
    f = open("tests/fixtures/Box.gltf")
    body = f.read()

    ioObj = six.StringIO(six.u(body))
    obj = wandb.Object3D(ioObj, file_type="obj")

    assert obj.extension == "obj"


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


def test_object3d_transform():
    obj = wandb.Object3D.transform([
        wandb.Object3D(open("tests/fixtures/Box.gltf")),
        wandb.Object3D(open("tests/fixtures/cube.obj")),
        wandb.Object3D(point_cloud_1)], "tests/output", "pc", 1)

    assert os.path.exists("tests/output/media/object3D/pc_1_0.gltf")
    assert os.path.exists("tests/output/media/object3D/pc_1_1.obj")
    assert os.path.exists(
        "tests/output/media/object3D/pc_1_2.pts.json")

    assert obj["_type"] == "object3D"
    assert obj["filenames"] == [
        "pc_1_0.gltf",
        "pc_1_1.obj",
        "pc_1_2.pts.json",
    ]


def test_table_init():
    table = wandb.Table(data=[["Some awesome text", "Positive", "Negative"]])
    assert wandb.Table.transform(table) == {"_type": "table",
                                            "data": [["Some awesome text", "Positive", "Negative"]],
                                            "columns": ["Input", "Output", "Expected"]}
