import wandb
from wandb import wandb_run
from wandb.keras import WandbCallback
import pytest
from click.testing import CliRunner
import os
import json
from .utils import git_repo
from keras.layers import Dense, Flatten, Reshape, Input, LSTM, Embedding, Input, Concatenate
from keras.models import Sequential, Model
from keras import backend as K
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
    assert len(run.summary["graph"]["nodes"]) == 3


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


def test_keras_convert_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    model = Sequential()
    model.add(Dense(4, input_shape=(3,)))
    model.add(Dense(5))
    model.add(Dense(6))
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph.transform(wandb_model)
    print(wandb_model_out)
    assert wandb_model_out == {'_type': 'graph', 'format': 'keras',
        'nodes': [
            {'name': 'dense_1', 'id': 'dense_1', 'class_name': 'Dense', 'output_shape': (None, 4), 'num_parameters': 16},
            {'name': 'dense_1_input', 'id': 'dense_1_input', 'class_name': 'InputLayer', 'output_shape': (None, 3), 'num_parameters': 0},
            {'name': 'dense_2', 'id': 'dense_2', 'class_name': 'Dense', 'output_shape': (None, 5), 'num_parameters': 25},
            { 'name': 'dense_3', 'id': 'dense_3', 'class_name': 'Dense', 'output_shape': (None, 6), 'num_parameters': 36}],
        'edges': [['dense_1_input', 'dense_1'], ['dense_1', 'dense_2'], ['dense_2', 'dense_3']]}

def test_keras_convert_model_non_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    # example from the Keras docs
    main_input = Input(shape=(100,), dtype='int32', name='main_input')
    x = Embedding(output_dim=512, input_dim=10000, input_length=100)(main_input)
    lstm_out = LSTM(32)(x)
    auxiliary_output = Dense(1, activation='sigmoid', name='aux_output')(lstm_out)
    auxiliary_input = Input(shape=(5,), name='aux_input')
    x = Concatenate()([lstm_out, auxiliary_input])
    x = Dense(64, activation='relu')(x)
    x = Dense(64, activation='relu')(x)
    x = Dense(64, activation='relu')(x)
    main_output = Dense(1, activation='sigmoid', name='main_output')(x)
    model = Model(inputs=[main_input, auxiliary_input], outputs=[main_output, auxiliary_output])
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph.transform(wandb_model)

    print(wandb_model_out['edges'])
    assert wandb_model_out['nodes'][0] == {'name': 'main_input', 'id': 'main_input', 'class_name': 'InputLayer', 'output_shape': (None, 100), 'num_parameters': 0}
    assert wandb_model_out['edges'] == [
            ['main_input', 'embedding_1'], ['embedding_1', 'lstm_1'], ['lstm_1', 'concatenate_1'],
            ['aux_input', 'concatenate_1'], ['concatenate_1', 'dense_1'], ['dense_1', 'dense_2'],
            ['dense_2', 'dense_3'], ['dense_3', 'main_output'], ['lstm_1', 'aux_output']]
