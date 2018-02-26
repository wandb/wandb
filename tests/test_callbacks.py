import wandb
from wandb import wandb_run
import pytest
from click.testing import CliRunner
import os
import json
from .utils import git_repo
from keras.layers import Dense
from keras.models import Sequential
import sys


@pytest.fixture
def dummy_model():
    model = Sequential()
    model.add(Dense(32, activation='relu', input_dim=10))
    model.add(Dense(1, activation='sigmoid'))
    model.compile(optimizer='rmsprop',
                  loss='binary_crossentropy',
                  metrics=['accuracy'])
    return model


@pytest.fixture
def dummy_data():
    import numpy as np
    data = np.random.random((100, 10))
    labels = np.random.randint(2, size=(100, 1))
    return (data, labels)


def test_basic_keras(dummy_model, dummy_data, git_repo):
    wandb.run = wandb_run.Run.from_environment_or_defaults()
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36,
                    callbacks=[wandb.callbacks.Keras()])
    assert wandb.run.summary["epoch"] == 1
