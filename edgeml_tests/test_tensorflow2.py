import tensorflow as tf
import numpy as np
import wandb
import pytest
import time
from absl import flags
from wandb.keras import WandbCallback
from tensorflow.keras import backend as K
import glob
import os

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True


def create_experiment_summary(num_units_list, dropout_rate_list, optimizer_list):
    from tensorboard.plugins.hparams import api_pb2
    from tensorboard.plugins.hparams import summary as hparams_summary
    from google.protobuf import struct_pb2
    num_units_list_val = struct_pb2.ListValue()
    num_units_list_val.extend(num_units_list)
    dropout_rate_list_val = struct_pb2.ListValue()
    dropout_rate_list_val.extend(dropout_rate_list)
    optimizer_list_val = struct_pb2.ListValue()
    optimizer_list_val.extend(optimizer_list)
    return hparams_summary.experiment_pb(
        # The hyperparameters being changed
        hparam_infos=[
            api_pb2.HParamInfo(name='num_units',
                               display_name='Number of units',
                               type=api_pb2.DATA_TYPE_FLOAT64,
                               domain_discrete=num_units_list_val),
            api_pb2.HParamInfo(name='dropout_rate',
                               display_name='Dropout rate',
                               type=api_pb2.DATA_TYPE_FLOAT64,
                               domain_discrete=dropout_rate_list_val),
            api_pb2.HParamInfo(name='optimizer',
                               display_name='Optimizer',
                               type=api_pb2.DATA_TYPE_STRING,
                               domain_discrete=optimizer_list_val)
        ],
        # The metrics being tracked
        metric_infos=[
            api_pb2.MetricInfo(
                name=api_pb2.MetricName(
                    tag='epoch_accuracy'),
                display_name='Accuracy'),
        ]
    )


@pytest.fixture
def model():
    K.clear_session()
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Dense(128, activation="relu"))
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(loss="sparse_categorical_crossentropy",
                  optimizer="sgd", metrics=["accuracy"])
    return model


@pytest.fixture
def image_model():
    K.clear_session()
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Conv2D(
        3, 3, activation="relu", input_shape=(28, 28, 1)))
    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(loss="sparse_categorical_crossentropy",
                  optimizer="sgd", metrics=["accuracy"])
    return model


def test_tfflags(wandb_init_run):
    FLAGS = flags.FLAGS
    flags.DEFINE_float('learning_rate', 0.01, 'Initial learning rate.')
    wandb.config.update(FLAGS)
    assert wandb_init_run.config['learning_rate'] == 0.01


def test_keras(wandb_init_run, model):
    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=1,
              validation_split=0.2, callbacks=[WandbCallback()])
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert [n.name for n in wandb_init_run.summary["graph"].nodes] == [
        "dense", "dense_1"]


@pytest.mark.mocked_run_manager()
def test_tensorboard_basic(wandb_init_run, model):
    wandb.tensorboard.patch(tensorboardX=False)
    cb = tf.keras.callbacks.TensorBoard(
        histogram_freq=1, log_dir=os.getcwd())
    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=5,
              validation_split=0.2, callbacks=[cb])
    wandb_init_run.run_manager.test_shutdown()
    print(wandb_init_run.history.rows[0].keys())
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert wandb_init_run.history.rows[-1]["_step"] == 8
    # TODO: No histos in eager mode with TF callback 1.0
    print("Last Row:", wandb_init_run.history.rows[-1])
    assert wandb_init_run.history.rows[-1]['train/sequential/dense_1/kernel_0']
    assert wandb_init_run.history.rows[-2]['validation/epoch_loss']
    # TODO: will change to 2 event files in V2 callback
    assert len(wandb_init_run.run_manager._user_file_policies['live']) == 2
    assert len(glob.glob(wandb_init_run.dir + "/train/*.tfevents.*")) == 2
    assert len(glob.glob(wandb_init_run.dir + "/validation/*.tfevents.*")) == 1


@pytest.mark.mocked_run_manager()
def test_tensorboard_no_save(wandb_init_run, model):
    wandb.tensorboard.patch(tensorboardX=False, save=False)
    cb = tf.keras.callbacks.TensorBoard(
        histogram_freq=1, log_dir=os.getcwd())
    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=5,
              validation_split=0.2, callbacks=[cb])
    wandb_init_run.run_manager.test_shutdown()
    print(wandb_init_run.history.rows[0].keys())
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert wandb_init_run.history.rows[-1]["_step"] == 8
    print("WHAT", wandb_init_run.history.rows[-1])
    assert wandb_init_run.history.rows[-1]['train/sequential/dense_1/kernel_0']
    assert len(wandb_init_run.run_manager._user_file_policies['live']) == 0


@pytest.mark.skip("TF-Nightly got rid of tf.summary.import_event")
@pytest.mark.mocked_run_manager()
def test_tensorboard_hyper_params(wandb_init_run, model):
    from tensorboard.plugins.hparams import api_pb2
    from tensorboard.plugins.hparams import summary as hparams_summary
    wandb.tensorboard.patch(tensorboardX=False)
    cb = tf.keras.callbacks.TensorBoard(
        histogram_freq=1, log_dir=wandb_init_run.dir)

    class HParams(tf.keras.callbacks.Callback):
        def on_train_begin(self, logs):
            # TODO: v2 of the callback has a "writers" object
            with cb._writers["train"].as_default():
                exp = create_experiment_summary(
                    [16, 32], [0.1, 0.5], ['adam', 'sgd'])
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=exp).SerializeToString())
                summary_start = hparams_summary.session_start_pb(
                    hparams={'num_units': 16, 'dropout_rate': 0.5, 'optimizer': 'adam'})
                summary_end = hparams_summary.session_end_pb(
                    api_pb2.STATUS_SUCCESS)
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=summary_start).SerializeToString())
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=summary_end).SerializeToString())

    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=5,
              validation_split=0.2, callbacks=[cb, HParams()])

    wandb_init_run.run_manager.test_shutdown()
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert wandb_init_run.history.rows[-1]["_step"] == 4
    print("KEYS", wandb_init_run.history.rows[-1].keys())
    assert wandb_init_run.config["dropout_rate"] == 0.5
    assert wandb_init_run.config["optimizer"] == "adam"


@pytest.mark.skipif(tf.__version__[0] == '2', reason='Users of validation_split must manually pass in a validation data generator.')
def test_tfkeras_validation_data_array(wandb_init_run, image_model):
    image_model.fit(np.ones((10, 28, 28, 1)), np.ones((10,)), epochs=1,
                    validation_split=0.2, callbacks=[WandbCallback(data_type="image")])
    print("WHOA", wandb_init_run.history.rows[0])
    assert wandb_init_run.history.rows[0]["examples"]["count"] == 2
    assert len(wandb_init_run.history.rows[0]["examples"]["captions"]) == 2


def test_tfkeras_no_validation_data(wandb_init_run, image_model, capsys):
    image_model.fit(np.ones((10, 28, 28, 1)), np.ones((10,)), epochs=1,
                    callbacks=[WandbCallback(data_type="image")])
    print("WHOA", wandb_init_run.history.rows[0])
    captured_out, captured_err = capsys.readouterr()
    assert "No validation_data set" not in captured_out
    assert wandb_init_run.history.rows[0].get("examples") is None


def test_tfkeras_validation_generator(wandb_init_run, image_model):
    def generator(*args):
        while True:
            yield (np.ones((2, 28, 28, 1)), np.ones((2,)))
    image_model.fit_generator(generator(), steps_per_epoch=10, epochs=2,
                              validation_data=generator(), validation_steps=2, callbacks=[WandbCallback(data_type="image")])
    print("WHOA", wandb_init_run.history.rows[0])
    assert wandb_init_run.history.rows[0]["examples"]["count"] == 2
    assert len(wandb_init_run.history.rows[0]["examples"]["captions"]) == 2


def test_tfkeras_tf_dataset(wandb_init_run, image_model):
    dataset = tf.data.Dataset.from_tensor_slices(
        (np.ones((10, 28, 28, 1)), np.ones((10,))))

    image_model.fit(dataset.batch(5).repeat(), steps_per_epoch=10, epochs=2,
                    validation_data=dataset.batch(5).repeat(), validation_steps=2, callbacks=[WandbCallback(data_type="image")])
    print("WHOA", wandb_init_run.history.rows[0])
    assert wandb_init_run.history.rows[0]["examples"] == {
        'width': 28, 'height': 28, 'count': 5, '_type': 'images', 'captions': [1, 1, 1, 1, 1]}
