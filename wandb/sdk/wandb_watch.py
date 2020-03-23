"""
watch.
"""

import wandb
import logging

logger = logging.getLogger("wandb")


def watch(models):
    logger.info("Watching")
    #wandb.run.watch(watch)
