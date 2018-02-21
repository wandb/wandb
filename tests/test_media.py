import wandb
import numpy as np
import PIL
import os
from click.testing import CliRunner

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
