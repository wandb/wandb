import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbCallback

run = wandb.init(project="keras")

np.random.seed(42)
x = np.random.randint(255, size=(100, 28, 28, 1))
y = np.random.randint(10, size=(100,))
dataset = (x, y)


def get_model():
    inputs = tf.keras.layers.Input(shape=(28,28,1))
    x = tf.keras.layers.Conv2D(3, 3, activation="relu")(inputs)
    x = tf.keras.layers.Flatten()(x)
    outputs = tf.keras.layers.Dense(10, activation="softmax")(x)

    return tf.keras.models.Model(inputs, outputs)

model = get_model()
model.compile(
    optimizer="sgd",
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"]
)

model.fit(
    x,
    y,
    epochs=2,
    validation_data=(x, y),
    callbacks=[WandbCallback()],
)