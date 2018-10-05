import wandb
import numpy as np
import pytest
import PIL
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from click.testing import CliRunner

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


def test_table_default():
    table = wandb.Table()
    table.add_row("Some awesome text", "Positive", "Negative")
    assert wandb.Table.transform(table) == {"_type": "table",
                                            "data": [["Some awesome text", "Positive", "Negative"]],
                                            "columns": ["Input", "Output", "Expected"]}


def test_table_custom():
    table = wandb.Table(["Foo", "Bar"])
    table.add_row("So", "Cool")
    table.add_row("&", "Rad")
    assert wandb.Table.transform(table) == {"_type": "table",
                                            "data": [["So", "Cool"], ["&", "Rad"]],
                                            "columns": ["Foo", "Bar"]}
