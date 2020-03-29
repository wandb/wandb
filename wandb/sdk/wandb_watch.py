"""
watch.
"""

import wandb
import logging

logger = logging.getLogger("wandb")


# NB: there is a copy of this in wand_run with the same signature
def watch(models, criterion=None, log="gradients", log_freq=100, idx=None):
    logger.info("Watching")
    #wandb.run.watch(watch)
