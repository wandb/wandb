import wandb
import numpy as np
import pytest
import PIL
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import soundfile
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
        meta = wandb.Audio.transform([wandb.Audio(audio, sample_rate=44100)], ".", "test", 0)
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
