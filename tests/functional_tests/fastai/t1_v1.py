import wandb
from fastai.vision import *  # noqa: F403
from wandb.fastai import WandbCallback

wandb.init()

path = untar_data(URLs.MNIST_SAMPLE)  # noqa: F405
data = ImageDataBunch.from_folder(path)  # noqa: F405
learn = Learner(
    data, simple_cnn((3, 16, 16, 2)), metrics=accuracy, callback_fns=WandbCallback
)  # noqa: F405
learn.fit(2)
