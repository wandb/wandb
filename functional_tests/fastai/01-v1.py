from fastai.vision import *  # noqa: F403
import wandb
from wandb.fastai import WandbCallback


path = untar_data(URLs.MNIST_SAMPLE)  # noqa: F405
data = ImageDataBunch.from_folder(path)  # noqa: F405
model = simple_cnn((3, 16, 16, 2))  # noqa: F405

wandb.init()

learn = cnn_learner(data, model, callback_fns=WandbCallback)  # noqa: F405
learn.fit(2)
