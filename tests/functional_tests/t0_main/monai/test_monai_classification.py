import logging
import os
import sys

import numpy as np
import torch
from ignite.engine import (
    Events,
    _prepare_batch,
    create_supervised_evaluator,
    create_supervised_trainer,
)
from ignite.handlers import EarlyStopping

import monai
from monai.data import decollate_batch, DataLoader
from monai.handlers import ROCAUC, StatsHandler, stopping_fn_from_metric
from monai.transforms import (
    Activations,
    AsDiscrete,
    Compose,
    LoadImaged,
    RandRotate90d,
    Resized,
    ScaleIntensityd,
)

import wandb
from wandb.integration.monai import WandbModelCheckpoint, WandbStatsHandler


def main():
    monai.config.print_config()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    wandb.init(project="monai-test", entity="geekyrakshit")
    config = wandb.config
    config.batch_size = 2
    config.num_workers = 4
    config.validation_every_n_epochs = 1
    config.lr = 1e-5
    config.train_epochs = 1

    # IXI dataset as a demo, original dataset downloadable from
    # https://brain-development.org/ixi-dataset/
    artifact = wandb.use_artifact("geekyrakshit/monai-test/ixi-dataset-t1:v0")
    data_path = artifact.download()
    images = [
        "IXI314-IOP-0889-T1.nii.gz",
        "IXI249-Guys-1072-T1.nii.gz",
        "IXI609-HH-2600-T1.nii.gz",
        "IXI173-HH-1590-T1.nii.gz",
        "IXI020-Guys-0700-T1.nii.gz",
        "IXI342-Guys-0909-T1.nii.gz",
        "IXI134-Guys-0780-T1.nii.gz",
        "IXI577-HH-2661-T1.nii.gz",
        "IXI066-Guys-0731-T1.nii.gz",
        "IXI130-HH-1528-T1.nii.gz",
        "IXI607-Guys-1097-T1.nii.gz",
        "IXI175-HH-1570-T1.nii.gz",
        "IXI385-HH-2078-T1.nii.gz",
        "IXI344-Guys-0905-T1.nii.gz",
        "IXI409-Guys-0960-T1.nii.gz",
        "IXI584-Guys-1129-T1.nii.gz",
        "IXI253-HH-1694-T1.nii.gz",
        "IXI092-HH-1436-T1.nii.gz",
        "IXI574-IOP-1156-T1.nii.gz",
        "IXI585-Guys-1130-T1.nii.gz",
    ]
    images = [os.sep.join([data_path, f]) for f in images]

    # 2 binary labels for gender classification: man and woman
    labels = np.array(
        [0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0], dtype=np.int64
    )
    train_files = [
        {"img": img, "label": label} for img, label in zip(images[:10], labels[:10])
    ]
    val_files = [
        {"img": img, "label": label} for img, label in zip(images[-10:], labels[-10:])
    ]

    # define transforms for image
    train_transforms = Compose(
        [
            LoadImaged(keys=["img"], ensure_channel_first=True),
            ScaleIntensityd(keys=["img"]),
            Resized(keys=["img"], spatial_size=(96, 96, 96)),
            RandRotate90d(keys=["img"], prob=0.8, spatial_axes=[0, 2]),
        ]
    )
    val_transforms = Compose(
        [
            LoadImaged(keys=["img"], ensure_channel_first=True),
            ScaleIntensityd(keys=["img"]),
            Resized(keys=["img"], spatial_size=(96, 96, 96)),
        ]
    )

    # define dataset, data loader
    check_ds = monai.data.Dataset(data=train_files, transform=train_transforms)
    check_loader = DataLoader(
        check_ds,
        batch_size=config.batch_size,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
    )
    check_data = monai.utils.misc.first(check_loader)
    print(check_data["img"].shape, check_data["label"])

    # create DenseNet121, CrossEntropyLoss and Adam optimizer
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = monai.networks.nets.DenseNet121(
        spatial_dims=3, in_channels=1, out_channels=2
    ).to(device)
    loss = torch.nn.CrossEntropyLoss()
    opt = torch.optim.Adam(net.parameters(), config.lr)

    # Ignite trainer expects batch=(img, label) and returns output=loss at every iteration,
    # user can add output_transform to return other values, like: y_pred, y, etc.
    def prepare_batch(batch, device=None, non_blocking=False):
        return _prepare_batch((batch["img"], batch["label"]), device, non_blocking)

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

    # WandbStatsHandler logs loss at every iteration and plots metrics at every epoch to Weights & Biases
    train_wandb_stats_handler = WandbStatsHandler(output_transform=lambda x: x)
    train_wandb_stats_handler.attach(trainer)

    metric_name = "AUC"
    # add evaluation metric to the evaluator engine
    val_metrics = {metric_name: ROCAUC()}

    post_label = Compose([AsDiscrete(to_onehot=2)])
    post_pred = Compose([Activations(softmax=True)])
    # Ignite evaluator expects batch=(img, label) and returns output=(y_pred, y) at every iteration,
    # user can add output_transform to return other values
    evaluator = create_supervised_evaluator(
        net,
        val_metrics,
        device,
        True,
        prepare_batch=prepare_batch,
        output_transform=lambda x, y, y_pred: (
            [post_pred(i) for i in decollate_batch(y_pred)],
            [post_label(i) for i in decollate_batch(y, detach=False)],
        ),
    )

    # add stats event handler to print validation stats via evaluator
    val_stats_handler = StatsHandler(
        name="evaluator",
        output_transform=lambda x: None,  # no need to print loss value, so disable per iteration output
        global_epoch_transform=lambda x: trainer.state.epoch,
    )  # fetch global epoch number from trainer
    val_stats_handler.attach(evaluator)

    # add handler to record metrics to Weights & Biases at every epoch
    val_wandb_stats_handler = WandbStatsHandler(
        output_transform=lambda x: None,
        global_epoch_transform=lambda x: trainer.state.epoch,
    )
    val_wandb_stats_handler.attach(evaluator)

    # add early stopping handler to evaluator
    early_stopper = EarlyStopping(
        patience=4, score_function=stopping_fn_from_metric(metric_name), trainer=trainer
    )
    evaluator.add_event_handler(
        event_name=Events.EPOCH_COMPLETED, handler=early_stopper
    )

    # create a validation data loader
    val_ds = monai.data.Dataset(data=val_files, transform=val_transforms)
    val_loader = DataLoader(
        val_ds,
        batch_size=2,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
    )

    @trainer.on(Events.EPOCH_COMPLETED(every=config.validation_every_n_epochs))
    def run_validation(engine):
        evaluator.run(val_loader)

    # create a training data loader
    train_ds = monai.data.Dataset(data=train_files, transform=train_transforms)
    train_loader = DataLoader(
        train_ds,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
    )

    state = trainer.run(train_loader, config.train_epochs)
    print(state)


if __name__ == "__main__":
    main()
