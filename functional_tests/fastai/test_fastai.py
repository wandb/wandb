from fastai.callback.wandb import *
from fastai.vision.all import *
import wandb

wandb.init(project="wandb_integrations_testing")
path = untar_data(URLs.MNIST_TINY)
mnist = DataBlock(
    blocks=(ImageBlock(cls=PILImageBW), CategoryBlock),
    get_items=get_image_files,
    splitter=GrandparentSplitter(),
    get_y=parent_label,
)

dls = mnist.dataloaders(path / "train", bs=32)
learn = cnn_learner(dls, resnet18, metrics=error_rate)
learn.fit(2, 1e-2, cbs=WandbCallback(log_preds=False, log_model=False))
wandb.finish()
