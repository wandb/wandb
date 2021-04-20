import wandb
import numpy as np
import time
import tensorflow as tf
import glob
import os

def main():
    #wandb.init(project="tf2", sync_tensorboard=True, resume=True)
    wandb.init(sync_tensorboard=True, resume=True)

    wandb.config['nice'] = 'So cool fun'


    class Logger(tf.keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs):
            time.sleep(2)
            wandb.log({"wild_metrics": logs, "interval": epoch * 10})


    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Conv2D(
        3, 3, activation="relu", input_shape=(28, 28, 1)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(loss="sparse_categorical_crossentropy",
                  optimizer="sgd", metrics=["accuracy"])

    model.fit(np.ones((10, 28, 28, 1)), np.ones((10,)), epochs=17,
              validation_split=0.2, callbacks=[Logger(), tf.keras.callbacks.TensorBoard()])

if __name__ == '__main__':
    main()
