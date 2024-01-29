#!/usr/bin/env python

from PIL import Image
import numpy as np
import pandas as pd
from wandb.integration.lightning.fabric.logger import WandbLogger


def test_wandblogger_functionality():
    logger = WandbLogger(project="fabric-test_logger_logging")
    logger.log_hyperparams({"lr": 0.001, "batch_size": 16})
    logger.log_metrics({"accuracy": 0.95, "loss": 0.05}, step=0)
    logger.log_image("test_image", [Image.fromarray((np.random.rand(100, 100, 3) * 255).astype(np.uint8))], step=0)
    logger.log_text("test_text", dataframe=pd.DataFrame({"Text": ["This is a test text."]}), step=0)
    logger.log_table("test_table", columns=["col1", "col2"], data=[["test", "table"]], step=0)
    logger.log_audio("test_audio", audios=[np.random.uniform(-1, 1, 44100)], step=0, sample_rate=[44100])
    logger.log_video("test_video", videos=[np.random.randint(256, size=(10, 50, 50, 3)).astype(np.uint8)], step=0, fps=[4])
    logger.finalize("success")

if __name__ == "__main__":
    test_wandblogger_functionality()