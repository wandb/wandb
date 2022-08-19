import pathlib

import keras  # noqa: F401
import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbCallback


def main():
    wandb.init(name=pathlib.Path(__file__).stem)

    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Conv2D(3, 3, activation="relu", input_shape=(28, 28, 1)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(
        loss="sparse_categorical_crossentropy", optimizer="sgd", metrics=["accuracy"]
    )

    model.fit(
        np.ones((10, 28, 28, 1)),
        np.ones((10,)),
        epochs=7,
        validation_split=0.2,
        callbacks=[WandbCallback()],
    )


if __name__ == "__main__":
    main()
