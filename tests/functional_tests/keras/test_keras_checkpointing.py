import os

import numpy as np
np.random.seed(0)
import tensorflow as tf
tf.random.set_seed(0)

import wandb
from wandb.keras import WandbCallback


class config:
    epochs = 10
    save_model_frequency = 5

config_dict = {k:v for k, v in vars(config).items() if '__' not in k}

x = np.random.randint(255, size=(100, 28, 28, 1)).astype(np.float32)
y = np.random.randint(10, size=(100,)).astype(np.float32)
dataset = (x, y)


class DummyModel(tf.keras.Model):
    def __init__(self, num_classes=10):
        super().__init__()
        self.conv = tf.keras.layers.Conv2D(
            3, 3, activation="relu", input_shape=(28, 28, 1)
        )
        self.flatten = tf.keras.layers.Flatten()
        self.classifier = tf.keras.layers.Dense(10, activation="softmax")

    def call(self, inputs):
        x = self.conv(inputs)
        x = self.flatten(x)
        return self.classifier(x)


model = DummyModel()
model.compile(
    loss="sparse_categorical_crossentropy", optimizer="sgd", metrics=["accuracy"]
)

run = wandb.init(project="keras", config=config_dict)

model.fit(
    x,
    y,
    epochs=config.epochs,
    validation_data=(x, y),
    callbacks=[WandbCallback(save_model=True, save_best_only=True, save_model_frequency=config.save_model_frequency)],
)
