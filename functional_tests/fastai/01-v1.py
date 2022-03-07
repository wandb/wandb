from fastai.vision import *
import wandb
from wandb.fastai import WandbCallback


path = untar_data(URLs.MNIST_SAMPLE)
data = ImageDataBunch.from_folder(path)

wandb.init()

learn = cnn_learner(data, model, callback_fns=WandbCallback)
learn.fit(2)
