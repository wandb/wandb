#!/usr/bin/env python

# https://github.com/wandb/examples/tree/master/examples/tensorboard/tensorboard-tf2-gradienttape
# https://www.tensorflow.org/tensorboard/get_started

import argparse
import datetime

import numpy as np
import tensorflow as tf
import wandb

parser = argparse.ArgumentParser()
parser.add_argument("--log_dir", type=str, help="Where to store tensorboard files")
args = parser.parse_args()

# We're defining some default hyper-parameters here, usually you'll
# use argparse or another config management tool as well
wandb.require("service")
config_defaults = dict(epochs=2, dropout=0.2, learning_rate=0.001)
wandb.init(config=config_defaults, sync_tensorboard=True)

mnist = tf.keras.datasets.mnist

(x_train, y_train), (x_test, y_test) = mnist.load_data()
x_train, x_test = x_train / 255.0, x_test / 255.0

train_dataset = tf.data.Dataset.from_tensor_slices((x_train, y_train))
test_dataset = tf.data.Dataset.from_tensor_slices((x_test, y_test))

train_dataset = train_dataset.shuffle(60000).batch(64)
test_dataset = test_dataset.batch(64)

loss_object = tf.keras.losses.SparseCategoricalCrossentropy()
optimizer = tf.keras.optimizers.Adam(learning_rate=wandb.config.learning_rate)

# Define our metrics
train_loss = tf.keras.metrics.Mean("train_loss", dtype=tf.float32)
train_accuracy = tf.keras.metrics.SparseCategoricalAccuracy("train_accuracy")
test_loss = tf.keras.metrics.Mean("test_loss", dtype=tf.float32)
test_accuracy = tf.keras.metrics.SparseCategoricalAccuracy("test_accuracy")


def train_step(model, optimizer, x_train, y_train):
    with tf.GradientTape() as tape:
        predictions = model(x_train, training=True)
        loss = loss_object(y_train, predictions)
    grads = tape.gradient(loss, model.trainable_variables)
    optimizer.apply_gradients(zip(grads, model.trainable_variables))

    train_loss(loss)
    train_accuracy(y_train, predictions)


def test_step(model, x_test, y_test):
    predictions = model(x_test)
    loss = loss_object(y_test, predictions)

    test_loss(loss)
    test_accuracy(y_test, predictions)


current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
log_base = args.log_dir or "logs/gradient_tape/"
train_log_dir = log_base + "/" + current_time + "/train"
test_log_dir = log_base + "/" + current_time + "/test"
train_summary_writer = tf.summary.create_file_writer(train_log_dir)
test_summary_writer = tf.summary.create_file_writer(test_log_dir)


def create_model():
    return tf.keras.models.Sequential(
        [
            tf.keras.layers.Flatten(input_shape=(28, 28)),
            tf.keras.layers.Dense(512, activation="relu"),
            tf.keras.layers.Dropout(wandb.config.dropout),
            tf.keras.layers.Dense(10, activation="softmax"),
        ]
    )


model = create_model()  # reset our model

EPOCHS = wandb.config.epochs

for epoch in range(EPOCHS):
    for (x_train, y_train) in train_dataset:
        train_step(model, optimizer, x_train, y_train)

    with train_summary_writer.as_default():
        tf.summary.scalar("loss", train_loss.result(), step=epoch)
        tf.summary.scalar("accuracy", train_accuracy.result(), step=epoch)

    images = None
    for (x_test, y_test) in test_dataset:
        test_step(model, x_test, y_test)
        if images is None:
            images = np.reshape(x_test[0:25], (-1, 28, 28, 1))

    with test_summary_writer.as_default():
        tf.summary.scalar("loss", test_loss.result(), step=epoch)
        tf.summary.scalar("accuracy", test_accuracy.result(), step=epoch)
        tf.summary.image("25 test data examples", images, max_outputs=25, step=epoch)

    template = "Epoch {}, Loss: {}, Accuracy: {}, Test Loss: {}, Test Accuracy: {}"
    print(
        template.format(
            epoch + 1,
            train_loss.result(),
            train_accuracy.result() * 100,
            test_loss.result(),
            test_accuracy.result() * 100,
        )
    )

    # Reset metrics every epoch
    train_loss.reset_states()
    test_loss.reset_states()
    train_accuracy.reset_states()
    test_accuracy.reset_states()

wandb.finish()
