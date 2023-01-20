import logging

import pytest


def test_logging(wandb_init):
    root_logger = logging.getLogger()
    root_logger.setLevel("DEBUG")
    root_logs = []
    root_handler = logging.Handler()
    root_handler.emit = lambda x: root_logs.append(x.msg)
    root_logger.addHandler(root_handler)

    wandb_logger = logging.getLogger("wandb")
    wandb_handler = logging.Handler()
    wandb_logs = []
    wandb_handler.emit = lambda x: wandb_logs.append(x.msg)
    wandb_logger.addHandler(wandb_handler)

    wandb_child_logger = logging.getLogger("wandb.x.y.z")
    wandb_child_handler = logging.Handler()
    wandb_child_logs = []
    wandb_child_handler.emit = lambda x: wandb_child_logs.append(x.msg)
    wandb_child_logger.addHandler(wandb_child_handler)

    root_logger.info("info1")
    root_logger.warn("warn1")

    run = wandb_init()

    root_logger.info("info2")
    root_logger.warn("warn2")

    wandb_logger.info("info3")
    wandb_logger.warn("warn3")

    wandb_child_logger.info("info4")
    wandb_child_logger.info("warn4")

    run.finish()

    root_logger.info("info5")
    root_logger.warn("warn5")

    # Work around unknown test flake WB-6348
    try:
        root_logs.remove("git repository is invalid")
    except ValueError:
        pass

    assert root_logs == ["info1", "warn1", "info2", "warn2", "info5", "warn5"]
    assert not any([msg in wandb_logs for msg in root_logs])
    assert all([msg in wandb_logs for msg in ["info3", "warn3", "info4", "warn4"]])
    assert wandb_child_logs == ["info4", "warn4"]
