import os

import numpy as np
import tensorflow as tf
from jax import random

import wandb

x = tf.random.uniform(shape=[3, 2, 7])

key = random.PRNGKey(42)
y = random.normal(key, shape=(2, 4, 6))

rng = np.random.default_rng(os.getpid())
height = width = 2

media = [wandb.Image(rng.random((height, width))) for _ in range(3)]

run = wandb.init()
run.log({"x": x})
run.summary["best_accuracy"] = [x, {"y": y}, {"z": 3, "a": {"seven": [x, y]}}]
# run.summary["best_accuracy"] = {"y": media}
run.finish()
