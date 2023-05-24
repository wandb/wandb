import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

# Create a sequential model
model = Sequential()
model.add(Dense(10, input_shape=(5,)))
model.add(Dense(1))
model.compile(optimizer="adam", loss="mse")

# Generate random data for training
import numpy as np

X = np.random.rand(100, 5)
y = np.random.rand(100, 1)

# Define the callbacks
early_stopping = EarlyStopping(patience=3)
checkpoint = ModelCheckpoint("model_checkpoint.h5", save_best_only=True)

# Fit the model with callbacks
model.fit(X, y, epochs=10, batch_size=32, callbacks=[early_stopping, checkpoint])
