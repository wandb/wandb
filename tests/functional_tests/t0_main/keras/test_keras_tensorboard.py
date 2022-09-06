import numpy as np
import tensorflow as tf
import wandb
from tensorflow.keras.callbacks import TensorBoard
from wandb.keras import WandbCallback

wandb.tensorboard.patch(root_logdir="logs")
run = wandb.init(project="keras")

x = np.random.randint(255, size=(100, 28, 28, 1))
y = np.random.randint(10, size=(100,))

dataset = (x, y)


model = tf.keras.Sequential()
model.add(tf.keras.layers.Conv2D(3, 3, activation="relu", input_shape=(28, 28, 1)))
model.add(tf.keras.layers.Flatten())
model.add(tf.keras.layers.Dense(10, activation="softmax"))
model.compile(
    loss="sparse_categorical_crossentropy", optimizer="sgd", metrics=["accuracy"]
)

model.fit(
    x,
    y,
    epochs=2,
    validation_data=(x, y),
    callbacks=[WandbCallback(input_type="image"), TensorBoard(log_dir="logs")],
)

run.finish()
