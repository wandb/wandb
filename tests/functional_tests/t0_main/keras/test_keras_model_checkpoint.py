import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbModelCheckpoint

tf.keras.utils.set_random_seed(1234)

run = wandb.init(project="keras")

x = np.random.randint(255, size=(100, 28, 28, 1))
y = np.random.randint(10, size=(100,))

dataset = (x, y)


def get_model():
    m = tf.keras.Sequential()
    m.add(tf.keras.layers.Conv2D(3, 3, activation="relu", input_shape=(28, 28, 1)))
    m.add(tf.keras.layers.Flatten())
    m.add(tf.keras.layers.Dense(10, activation="softmax"))
    return m


model = get_model()
model.compile(
    loss="sparse_categorical_crossentropy",
    optimizer="sgd",
    metrics=["accuracy"],
)

model.fit(
    x,
    y,
    epochs=2,
    validation_data=(x, y),
    callbacks=[
        WandbModelCheckpoint(
            filepath="wandb/model/model_{epoch}",
            monitor="accuracy",
            save_best_only=True,
            save_weights_only=False,
            save_freq=1,
        )
    ],
)
