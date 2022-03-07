from fastai.vision import *  # noqa: F403
import wandb
from wandb.fastai import WandbCallback


wandb.init()

path = untar_data(URLs.MNIST_SAMPLE)  # noqa: F405
data = ImageDataBunch.from_folder(path)  # noqa: F405
learn = cnn_learner(data, models.resnet18, metrics=accuracy, callback_fns=WandbCallback)  # noqa: F405
learn.fit(1)
