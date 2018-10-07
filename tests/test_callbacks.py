import wandb
from wandb import wandb_run
from wandb.keras import WandbCallback
import pytest
from click.testing import CliRunner
import os
import json
from .utils import git_repo
from keras.layers import Dense, Flatten, Reshape
from keras.models import Sequential
import sys
import glob


@pytest.fixture
def dummy_model(request):
    multi = request.node.get_marker('multiclass')
    image_output = request.node.get_marker('image_output')
    if multi:
        nodes = 10
        loss = 'categorical_crossentropy'
    else:
        nodes = 1
        loss = 'binary_crossentropy'
    nodes = 1 if not multi else 10
    if image_output:
        nodes = 300
    model = Sequential()
    model.add(Flatten(input_shape=(10, 10, 3)))
    model.add(Dense(nodes, activation='sigmoid'))
    if image_output:
        model.add(Dense(nodes, activation="relu"))
        model.add(Reshape((10, 10, 3)))
    model.compile(optimizer='adam',
                  loss=loss,
                  metrics=['accuracy'])
    return model


@pytest.fixture
def dummy_data(request):
    multi = request.node.get_marker('multiclass')
    image_output = request.node.get_marker('image_output')
    cats = 10 if multi else 1
    import numpy as np
    data = np.random.randint(255, size=(100, 10, 10, 3))
    labels = np.random.randint(2, size=(100, cats))
    if image_output:
        labels = data
    return (data, labels)


@pytest.fixture
def run():
    return wandb_run.Run.from_environment_or_defaults()


def test_basic_keras(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36,
                    callbacks=[WandbCallback()])
    wandb.run.summary.load()
    assert run.history.rows[0]["epoch"] == 0
    assert run.summary["acc"] > 0
    assert len(run.summary["graph"]["nodes"]) == 2


def test_keras_image_bad_data(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    error = False
    data, labels = dummy_data

    try:
        dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=(data.reshape(10), labels),
                        callbacks=[WandbCallback(data_type="image")])
    except ValueError:
        error = True
    assert error


def test_keras_image_binary(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image")])
    assert len(run.history.rows[0]["examples"]['captions']) == 36


def test_keras_image_binary_captions(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10, labels=["Rad", "Nice"])])
    print(run.history.rows[0])
    assert run.history.rows[0]["examples"]['captions'][0] in ["Rad", "Nice"]


@pytest.mark.multiclass
def test_keras_image_multiclass(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10)])
    print(run.history.rows[0])
    assert len(run.history.rows[0]["examples"]['captions']) == 10


@pytest.mark.multiclass
def test_keras_image_multiclass_captions(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10, labels=["Rad", "Nice", "Fun", "Rad", "Nice", "Fun", "Rad", "Nice", "Fun", "Rad"])])
    print(run.history.rows[0])
    assert run.history.rows[0]["examples"]['captions'][0] in [
        "Rad", "Nice", "Fun"]


@pytest.mark.image_output
def test_keras_image_output(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10)])
    assert run.history.rows[0]["examples"]['count'] == 30
    assert run.history.rows[0]["examples"]['grouping'] == 3


def test_keras_log_weights(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", log_weights=True)])
    print("WHOA", run.history.rows[0].keys())
    assert run.history.rows[0]['dense_9.weights']['_type'] == "histogram"


def test_keras_save_model(dummy_model, dummy_data, git_repo, run):
    wandb.run = run
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", save_model=True)])
    assert len(glob.glob(run.dir + "/model-best.h5")) == 1
