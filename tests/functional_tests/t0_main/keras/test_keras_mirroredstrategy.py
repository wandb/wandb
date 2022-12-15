import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbCallback


def main():
    tf.keras.utils.set_random_seed(1234)

    def get_model():
        inputs = tf.keras.layers.Input(shape=(28, 28, 1))
        x = tf.keras.layers.Conv2D(3, 3, activation="relu")(inputs)
        x = tf.keras.layers.Flatten()(x)
        outputs = tf.keras.layers.Dense(10, activation="softmax")(x)

        model = tf.keras.models.Model(inputs, outputs)
        model.compile(
            optimizer="sgd",
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

        return model

    strategy = tf.distribute.MirroredStrategy()

    with strategy.scope():
        model = get_model()

    x = np.random.randint(255, size=(100, 28, 28, 1))
    y = np.random.randint(10, size=(100,))

    wandb.init(project="keras")

    model.fit(x, y, epochs=2, callbacks=WandbCallback())
    model.fit(x, y, epochs=2, callbacks=WandbCallback(compute_flops=True))


if __name__ == "__main__":
    main()
