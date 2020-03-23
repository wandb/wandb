"""
save.
"""

import wandb
import logging

logger = logging.getLogger("wandb")


def save(path, overwrite=None):
    logger.info("Saving file: %s", path)
    wandb.run.save(path)
