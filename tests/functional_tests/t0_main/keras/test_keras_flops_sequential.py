import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbCallback

run = wandb.init(project="keras")

np.random.seed(42)
x = np.random.randint(255, size=(100, 28, 28, 1))
y = np.random.randint(10, size=(100,))
dataset = (x, y)


def get_sequential_model():
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Conv2D(3, 3, activation="relu", input_shape=(28, 28, 1)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(
        optimizer="sgd", loss="sparse_categorical_crossentropy", metrics=["accuracy"]
    )

    return model


model = get_sequential_model()
_ = model.fit(x, y, epochs=2, callbacks=[WandbCallback()])
