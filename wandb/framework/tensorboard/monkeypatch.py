"""
monkeypatch: patch code to add tensorboard hooks
"""

import os
import sys

import wandb


TENSORBOARD_C_MODULE = "tensorflow.python.ops.gen_summary_ops"
TENSORBOARD_PYTORCH_MODULE = "tensorboard.summary.writer.event_file_writer"
REMOTE_FILE_TOKEN = "://"


def patch(save=None, tensorboardX=None, pytorch=None):
    if len(wandb.patched["tensorboard"]) > 0:
        raise ValueError(
            "Tensorboard already patched, remove sync_tensorboard=True from wandb.init or only call wandb.tensorboard.patch once."
        )

    wandb.util.get_module("tensorboard", required="Please install tensorboard package")
    c_writer = wandb.util.get_module(TENSORBOARD_C_MODULE)
    tb_writer = wandb.util.get_module(TENSORBOARD_PYTORCH_MODULE)

    if c_writer:
        _patch_tensorflow2(writer=c_writer, module=TENSORBOARD_C_MODULE, save=save)
    elif tb_writer:
        _patch_nontensorflow(
            writer=tb_writer, module=TENSORBOARD_PYTORCH_MODULE, save=save
        )
    else:
        wandb.termerror("Unsupported tensorboard configuration")


def _patch_tensorflow2(writer, module, save=None):
    # This configures TensorFlow 2 style Tensorboard logging
    old_csfw_func = writer.create_summary_file_writer

    def new_csfw_func(*args, **kwargs):
        logdir = (
            kwargs["logdir"].numpy().decode("utf8")
            if hasattr(kwargs["logdir"], "numpy")
            else kwargs["logdir"]
        )
        _notify_tensorboard_logdir(logdir, save=save)
        return old_csfw_func(*args, **kwargs)

    writer.orig_create_summary_file_writer = old_csfw_func
    writer.create_summary_file_writer = new_csfw_func
    wandb.patched["tensorboard"].append([module, "create_summary_file_writer"])


def _patch_nontensorflow(writer, module, save=None):
    # This configures non-TensorFlow Tensorboard logging
    old_efw_class = writer.EventFileWriter

    class TBXEventFileWriter(old_efw_class):
        def __init__(self, logdir, *args, **kwargs):
            _notify_tensorboard_logdir(logdir, save=save)
            super(TBXEventFileWriter, self).__init__(logdir, *args, **kwargs)

    writer.orig_EventFileWriter = old_efw_class
    writer.EventFileWriter = TBXEventFileWriter
    wandb.patched["tensorboard"].append([module, "EventFileWriter"])


def _notify_tensorboard_logdir(logdir, save=None):
    if REMOTE_FILE_TOKEN in logdir:
        wandb.termerror("Can not handle tensorboard_sync remote files: %s" % logdir)
        return
    wandb.run._tensorboard_callback(logdir, save=save)
