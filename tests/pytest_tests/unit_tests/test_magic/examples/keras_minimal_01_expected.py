import wandb

wandb.init()

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense

# Create a sequential model
model = Sequential()

# Add a single dense layer with 10 units and input shape of 5
model.add(Dense(10, input_shape=(5,)))

# Add an output layer with 1 unit
model.add(Dense(1))

# Compile the model
model.compile(optimizer="adam", loss="mse")

# Generate some random data for training
import numpy as np

X = np.random.rand(100, 5)
y = np.random.rand(100, 1)

# Fit the model
model.fit(X, y, epochs=10, batch_size=32, callbacks=[wandb.keras.WandbCallback()])
