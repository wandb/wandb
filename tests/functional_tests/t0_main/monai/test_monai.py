import logging
import os
import sys
import tempfile
from glob import glob

import monai
import nibabel as nib
import numpy as np
import torch
import wandb
from ignite.engine import (
    Events,
    _prepare_batch,
    create_supervised_evaluator,
    create_supervised_trainer,
)
from ignite.handlers import EarlyStopping
from monai.data import create_test_image_3d, decollate_batch, list_data_collate
from monai.handlers import MeanDice, StatsHandler, stopping_fn_from_metric
from monai.transforms import (
    Activations,
    AsDiscrete,
    Compose,
    EnsureChannelFirstd,
    LoadImaged,
    RandCropByPosNegLabeld,
    RandRotate90d,
    ScaleIntensityd,
)
from torch.utils.data import DataLoader
from wandb.integration.monai import WandbModelCheckpoint, WandbStatsHandler


def main(tempdir):
    monai.config.print_config()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    wandb.init()
    config = wandb.config
    config.train_batch_size = 2
    config.val_batch_size = 5
    config.epochs = 2

    # create a temporary directory and 40 random image, mask pairs
    print(f"generating synthetic data to {tempdir} (this may take a while)")
    for i in range(40):
        im, seg = create_test_image_3d(128, 128, 128, num_seg_classes=1, channel_dim=-1)

        n = nib.Nifti1Image(im, np.eye(4))
        nib.save(n, os.path.join(tempdir, f"img{i:d}.nii.gz"))

        n = nib.Nifti1Image(seg, np.eye(4))
        nib.save(n, os.path.join(tempdir, f"seg{i:d}.nii.gz"))

    images = sorted(glob(os.path.join(tempdir, "img*.nii.gz")))
    segs = sorted(glob(os.path.join(tempdir, "seg*.nii.gz")))
    train_files = [{"img": img, "seg": seg} for img, seg in zip(images[:20], segs[:20])]
    val_files = [{"img": img, "seg": seg} for img, seg in zip(images[-20:], segs[-20:])]

    # define transforms for image and segmentation
    train_transforms = Compose(
        [
            LoadImaged(keys=["img", "seg"]),
            EnsureChannelFirstd(keys=["img", "seg"]),
            ScaleIntensityd(keys="img"),
            RandCropByPosNegLabeld(
                keys=["img", "seg"],
                label_key="seg",
                spatial_size=[96, 96, 96],
                pos=1,
                neg=1,
                num_samples=4,
            ),
            RandRotate90d(keys=["img", "seg"], prob=0.5, spatial_axes=[0, 2]),
        ]
    )
    val_transforms = Compose(
        [
            LoadImaged(keys=["img", "seg"]),
            EnsureChannelFirstd(keys=["img", "seg"]),
            ScaleIntensityd(keys="img"),
        ]
    )

    # create a training data loader
    train_ds = monai.data.Dataset(data=train_files, transform=train_transforms)
    train_loader = DataLoader(
        train_ds,
        batch_size=config.train_batch_size,
        shuffle=True,
        num_workers=4,
        collate_fn=list_data_collate,
        pin_memory=torch.cuda.is_available(),
    )
    # create a validation data loader
    val_ds = monai.data.Dataset(data=val_files, transform=val_transforms)
    val_loader = DataLoader(
        val_ds,
        batch_size=config.val_batch_size,
        num_workers=8,
        collate_fn=list_data_collate,
        pin_memory=torch.cuda.is_available(),
    )

    # create UNet, DiceLoss and Adam optimizer
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = monai.networks.nets.UNet(
        spatial_dims=3,
        in_channels=1,
        out_channels=1,
        channels=(16, 32, 64, 128, 256),
        strides=(2, 2, 2, 2),
        num_res_units=2,
    ).to(device)
    loss = monai.losses.DiceLoss(sigmoid=True)
    lr = 1e-3
    opt = torch.optim.Adam(net.parameters(), lr)

    # Ignite trainer expects batch=(img, seg) and returns output=loss at every iteration,
    # user can add output_transform to return other values, like: y_pred, y, etc.
    def prepare_batch(batch, device=None, non_blocking=False):
        return _prepare_batch((batch["img"], batch["seg"]), device, non_blocking)

    trainer = create_supervised_trainer(
        net, opt, loss, device, False, prepare_batch=prepare_batch
    )

    # adding checkpoint handler to save models (network params and optimizer stats) during training
    checkpoint_handler = WandbModelCheckpoint(
        "./runs_dict/", "net", n_saved=10, require_empty=False
    )
    trainer.add_event_handler(
        event_name=Events.EPOCH_COMPLETED,
        handler=checkpoint_handler,
        to_save={"net": net, "opt": opt},
    )

    # StatsHandler prints loss at every iteration and print metrics at every epoch,
    # we don't set metrics for trainer here, so just print loss, user can also customize print functions
    # and can use output_transform to convert engine.state.output if it's not loss value
    train_stats_handler = StatsHandler(name="trainer", output_transform=lambda x: x)
    train_stats_handler.attach(trainer)

    # TensorBoardStatsHandler plots loss at every iteration and plots metrics at every epoch, same as StatsHandler
    train_wandb_stats_handler = WandbStatsHandler(output_transform=lambda x: x)
    train_wandb_stats_handler.attach(trainer)

    validation_every_n_iters = 5
    # set parameters for validation
    metric_name = "Mean_Dice"
    # add evaluation metric to the evaluator engine
    val_metrics = {metric_name: MeanDice()}

    post_pred = Compose([Activations(sigmoid=True), AsDiscrete(threshold=0.5)])
    post_label = Compose([AsDiscrete(threshold=0.5)])

    # Ignite evaluator expects batch=(img, seg) and returns output=(y_pred, y) at every iteration,
    # user can add output_transform to return other values
    evaluator = create_supervised_evaluator(
        net,
        val_metrics,
        device,
        True,
        output_transform=lambda x, y, y_pred: (
            [post_pred(i) for i in decollate_batch(y_pred)],
            [post_label(i) for i in decollate_batch(y)],
        ),
        prepare_batch=prepare_batch,
    )

    @trainer.on(Events.ITERATION_COMPLETED(every=validation_every_n_iters))
    def run_validation(engine):
        evaluator.run(val_loader)

    # add early stopping handler to evaluator
    early_stopper = EarlyStopping(
        patience=4, score_function=stopping_fn_from_metric(metric_name), trainer=trainer
    )
    evaluator.add_event_handler(
        event_name=Events.EPOCH_COMPLETED, handler=early_stopper
    )

    # add stats event handler to print validation stats via evaluator
    val_stats_handler = StatsHandler(
        name="evaluator",
        output_transform=lambda x: None,  # no need to print loss value, so disable per iteration output
        global_epoch_transform=lambda x: trainer.state.epoch,
    )  # fetch global epoch number from trainer
    val_stats_handler.attach(evaluator)

    # add handler to record metrics to TensorBoard at every validation epoch
    val_wandb_stats_handler = WandbStatsHandler(
        output_transform=lambda x: None,  # no need to plot loss value, so disable per iteration output
        global_epoch_transform=lambda x: trainer.state.iteration,
    )  # fetch global iteration number from trainer
    val_wandb_stats_handler.attach(evaluator)

    state = trainer.run(train_loader, config.epochs)
    print(state)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tempdir:
        main(tempdir)
