from __future__ import annotations

import tensorflow as tf
import wandb
from wandb.integration.keras import WandbCallback


def main():
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Conv2D(3, 3, activation="relu", input_shape=(28, 28, 1)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(
        loss="sparse_categorical_crossentropy", optimizer="sgd", metrics=["accuracy"]
    )

    with wandb.init(
        project="keras",
    ):
        model.fit(
            tf.ones((10, 28, 28, 1)),
            tf.ones((10,)),
            epochs=7,
            validation_split=0.2,
            callbacks=[
                WandbCallback(
                    save_graph=False,  # wandb implementation is broken
                    save_model=False,  # wandb implementation is broken
                )
            ],
        )


if __name__ == "__main__":
    main()
