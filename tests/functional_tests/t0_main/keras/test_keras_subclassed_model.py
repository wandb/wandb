import os

import numpy as np
import tensorflow as tf
import wandb
from wandb.keras import WandbCallback

run = wandb.init(project="keras")


x = np.random.randint(255, size=(100, 28, 28, 1)).astype(np.float32)
y = np.random.randint(10, size=(100,)).astype(np.float32)

dataset = (x, y)


class DummyModel(tf.keras.Model):
    def __init__(self, num_classes=10):
        super().__init__()
        self.conv = tf.keras.layers.Conv2D(
            3, 3, activation="relu", input_shape=(28, 28, 1)
        )
        self.flatten = tf.keras.layers.Flatten()
        self.classifier = tf.keras.layers.Dense(10, activation="softmax")

    def call(self, inputs):
        x = self.conv(inputs)
        x = self.flatten(x)
        return self.classifier(x)


model = DummyModel()

model.compile(
    loss="sparse_categorical_crossentropy", optimizer="sgd", metrics=["accuracy"]
)

model.fit(
    x,
    y,
    epochs=2,
    validation_data=(x, y),
    callbacks=[WandbCallback()],
)

# Finishing the run to upload the artifact.
# This is needed to test if the SavedModel model was logged.
run.finish()

api = wandb.Api()
artifact = api.artifact(f"{run.project}/model-{run.name}:latest")
download_dir = artifact.download()
files = sorted(os.listdir(download_dir))
print(f"FILES: {files}")
assert files[0] == "keras_metadata.pb"
assert files[1] == "saved_model.pb"
assert files[2] == "variables"
