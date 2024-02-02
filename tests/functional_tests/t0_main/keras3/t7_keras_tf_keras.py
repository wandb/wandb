import numpy as np
import tensorflow as tf
import wandb
from wandb.integration.keras3 import WandbMetricsLogger, WandbModelCheckpoint

wandb.init()
config = wandb.config
config.num_classes = 10
config.input_shape = (28, 28, 1)
config.batch_size = 128
config.epochs = 3
(x_train, y_train), (x_test, y_test) = tf.keras.datasets.mnist.load_data()
x_train = x_train[:10]
y_train = y_train[:10]
x_test = x_test[:10]
y_test = y_test[:10]
x_train = x_train.astype("float32") / 255
x_test = x_test.astype("float32") / 255
x_train = np.expand_dims(x_train, -1)
x_test = np.expand_dims(x_test, -1)
y_train = tf.keras.utils.to_categorical(y_train, config.num_classes)
y_test = tf.keras.utils.to_categorical(y_test, config.num_classes)
model = tf.keras.Sequential(
    [
        tf.keras.layers.Input(shape=config.input_shape),
        tf.keras.layers.Conv2D(32, kernel_size=(3, 3), activation="relu"),
        tf.keras.layers.MaxPooling2D(pool_size=(2, 2)),
        tf.keras.layers.Conv2D(64, kernel_size=(3, 3), activation="relu"),
        tf.keras.layers.MaxPooling2D(pool_size=(2, 2)),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dropout(0.5),
        tf.keras.layers.Dense(config.num_classes, activation="softmax"),
    ]
)
model.compile(loss="categorical_crossentropy", optimizer="adam", metrics=["accuracy"])
model.fit(
    x_train,
    y_train,
    batch_size=config.batch_size,
    epochs=config.epochs,
    validation_split=0.1,
    callbacks=[
        WandbMetricsLogger(log_freq="batch"),
        WandbModelCheckpoint(filepath="model.keras"),
    ],
)
