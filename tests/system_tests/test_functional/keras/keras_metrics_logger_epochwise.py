from __future__ import annotations

import numpy as np
import tensorflow as tf
import wandb
from wandb.integration.keras import WandbMetricsLogger

tf.keras.utils.set_random_seed(1234)

run = wandb.init(project="keras")

x = np.random.randint(255, size=(100, 28, 28, 1))
y = np.random.randint(10, size=(100,))

dataset = (x, y)


def get_model():
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.InputLayer(shape=(28, 28, 1)))
    model.add(tf.keras.layers.Conv2D(3, 3, activation="relu"))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    return model


model = get_model()

learning_rate = tf.keras.optimizers.schedules.ExponentialDecay(
    initial_learning_rate=0.1, decay_steps=2, decay_rate=0.1
)
opt = tf.keras.optimizers.SGD(learning_rate=learning_rate)

model.compile(
    loss="sparse_categorical_crossentropy", optimizer=opt, metrics=["accuracy"]
)


model.fit(
    x,
    y,
    epochs=2,
    validation_data=(x, y),
    callbacks=[
        WandbMetricsLogger(),
    ],
)

run.finish()
