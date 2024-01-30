import os

import keras
import numpy as np
import wandb
from keras import layers
from keras.utils import to_categorical
from wandb.integration.keras3 import WandbMetricsLogger

os.environ["KERAS_BACKEND"] = "torch"


wandb.init()
config = wandb.config
config.num_classes = 10
config.input_shape = (28, 28, 1)
config.batch_size = 128
config.epochs = 3
(x_train, y_train), (x_test, y_test) = keras.datasets.mnist.load_data()
x_train = x_train[:10]
y_train = y_train[:10]
x_test = x_test[:10]
y_test = y_test[:10]
x_train = x_train.astype("float32") / 255
x_test = x_test.astype("float32") / 255
x_train = np.expand_dims(x_train, -1)
x_test = np.expand_dims(x_test, -1)
y_train = to_categorical(y_train, config.num_classes)
y_test = to_categorical(y_test, config.num_classes)
model = keras.Sequential(
    [
        layers.Input(shape=config.input_shape),
        layers.Conv2D(32, kernel_size=(3, 3), activation="relu"),
        layers.MaxPooling2D(pool_size=(2, 2)),
        layers.Conv2D(64, kernel_size=(3, 3), activation="relu"),
        layers.MaxPooling2D(pool_size=(2, 2)),
        layers.Flatten(),
        layers.Dropout(0.5),
        layers.Dense(config.num_classes, activation="softmax"),
    ]
)
lr_schedule = keras.optimizers.schedules.PolynomialDecay(
    initial_learning_rate=1e-3,
    decay_steps=300,
    end_learning_rate=1e-8,
    power=0.99,
)
optimizer = keras.optimizers.Adam(learning_rate=lr_schedule, weight_decay=0.99)
model.compile(
    loss="categorical_crossentropy", optimizer=optimizer, metrics=["accuracy"]
)
model.fit(
    x_train,
    y_train,
    batch_size=config.batch_size,
    epochs=config.epochs,
    validation_split=0.1,
    callbacks=[WandbMetricsLogger(log_freq="batch")],
)
