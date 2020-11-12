"""
monkeypatch: patch code to add tensorboard hooks
"""

import wandb


TENSORBOARD_C_MODULE = "tensorflow.python.ops.gen_summary_ops"
TENSORBOARD_WRITER_MODULE = "tensorboard.summary.writer.event_file_writer"
TENSORBOARD_PYTORCH_MODULE = "torch.utils.tensorboard.writer"


def patch(save=None, tensorboardX=None, pytorch=None, logdir=None):
    if len(wandb.patched["tensorboard"]) > 0:
        raise ValueError(
            "Tensorboard already patched, remove sync_tensorboard=True from wandb.init or only call wandb.tensorboard.patch once."
        )

    wandb.util.get_module("tensorboard", required="Please install tensorboard package")
    c_writer = wandb.util.get_module(TENSORBOARD_C_MODULE)
    tb_writer = wandb.util.get_module(TENSORBOARD_WRITER_MODULE)
    pt_writer = wandb.util.get_module(TENSORBOARD_PYTORCH_MODULE)

    if not pytorch and not tensorboardX and c_writer:
        _patch_tensorflow2(
            writer=c_writer, module=TENSORBOARD_C_MODULE, save=save, logdir=logdir
        )
    if tb_writer:
        if logdir is not None:
            tb_writer.logdir = logdir
        _patch_nontensorflow(
            writer=tb_writer, module=TENSORBOARD_WRITER_MODULE, save=save, logdir=logdir
        )
    if pt_writer:
        _patch_nontensorflow(
            writer=pt_writer,
            module=TENSORBOARD_PYTORCH_MODULE,
            save=save,
            logdir=logdir,
        )
    if not c_writer and not tb_writer and not tb_writer:
        wandb.termerror("Unsupported tensorboard configuration")


def _patch_tensorflow2(writer, module, save=None, logdir=None, old_logdir=None):
    # This configures TensorFlow 2 style Tensorboard logging
    old_csfw_func = writer.create_summary_file_writer
    tboard_logdir = logdir
    logdir_hist = []

    def new_csfw_func(*args, **kwargs):
        logdir = (
            kwargs["logdir"].numpy().decode("utf8")
            if hasattr(kwargs["logdir"], "numpy")
            else kwargs["logdir"]
        )
        logdir_hist.append(logdir)

        if len(set(logdir_hist)) > 1 and tboard_logdir is None:
            wandb.termwarn(
                "When using several event log directories, please specify the root log directory in wandb.init"
            )

        _notify_tensorboard_logdir(logdir, save=save, tboard_logdir=tboard_logdir)
        return old_csfw_func(*args, **kwargs)

    writer.orig_create_summary_file_writer = old_csfw_func
    writer.create_summary_file_writer = new_csfw_func
    wandb.patched["tensorboard"].append([module, "create_summary_file_writer"])


def _patch_nontensorflow(writer, module, save=None, logdir=None, old_logdir=None):
    # This configures non-TensorFlow Tensorboard logging
    old_efw_class = writer.EventFileWriter
    tboard_logdir = logdir

    logdir_hist = []

    class TBXEventFileWriter(old_efw_class):
        def __init__(self, logdir, *args, **kwargs):
            logdir_hist.append(logdir)
            if len(set(logdir_hist)) > 1:
                wandb.termwarn(
                    "When using several event log directories, please specify the root log directory in wandb.init"
                )
            _notify_tensorboard_logdir(logdir, save=save, tboard_logdir=tboard_logdir)

            super(TBXEventFileWriter, self).__init__(logdir, *args, **kwargs)

    writer.orig_EventFileWriter = old_efw_class
    writer.EventFileWriter = TBXEventFileWriter
    wandb.patched["tensorboard"].append([module, "EventFileWriter"])


def _notify_tensorboard_logdir(logdir, save=None, tboard_logdir=None):
    wandb.run._tensorboard_callback(logdir, save=save, tboard_logdir=tboard_logdir)
