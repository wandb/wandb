import argparse
import copy
import json
import os
import re
import sys

import yaml

import wandb
from wandb import trigger
from wandb.util import add_import_hook, get_optional_module

_import_hook = None
_run_once = False
_args_argparse = None
_args_system = None
_args_absl = None
_magic_init_seen = False
_magic_config = {}


class ArgumentException(Exception):
    pass


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentException()


def _merge_dicts(source, destination):
    for key, value in source.items():
        if isinstance(value, dict):
            node = destination.setdefault(key, {})
            _merge_dicts(value, node)
        else:
            destination[key] = value
    return destination


def _dict_from_keyval(k, v, json_parse=True):
    d = ret = {}
    keys = k.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    if json_parse:
        try:
            v = json.loads(v.strip('"'))
        except ValueError:
            pass
    d[keys[-1]] = v
    return ret


def _magic_get_config(k, default):
    d = _magic_config
    keys = k.split(".")
    for k in keys[:-1]:
        d = d.get(k, {})
    return d.get(keys[-1], default)


_magic_defaults = {
    "enable": None,
    #'wandb': {
    #    'disable': None,
    # },
    "keras": {
        "fit": {
            "callbacks": {
                "tensorboard": {
                    "enable": True,
                    "duplicate": False,
                    "overwrite": False,
                    "write_graph": None,
                    "histogram_freq": None,
                    "update_freq": None,
                    "write_grads": None,
                    "write_images": None,
                    "batch_size": None,
                },
                "wandb": {
                    "enable": True,
                    "duplicate": False,
                    "overwrite": False,
                    "log_gradients": None,
                    "log_weights": None,
                    "data_type": "auto",
                    "input_type": None,
                    "output_type": None,
                    "log_evaluation": None,
                    "labels": None,
                    "predictions": None,
                    "save_model": None,
                    "save_weights_only": None,
                    "monitor": None,
                    "mode": None,
                    "verbose": None,
                },
                "epochs": None,
                "batch_size": None,
            }
        },
        #'compile': {
        #       'optimizer': {
        #           'name': False,
        #           },
        #       'loss': None,
        #    },
    },
    "args": {
        "absl": None,
        "argparse": None,
        "sys": None,
    },
}


def _parse_magic(val):
    # attempt to treat string as a json
    not_set = {}
    if val is None:
        return _magic_defaults, not_set
    if val.startswith("{"):
        try:
            val = json.loads(val)
        except ValueError:
            wandb.termwarn("Unable to parse magic json", repeat=False)
            return _magic_defaults, not_set
        conf = _merge_dicts(_magic_defaults, {})
        return _merge_dicts(val, conf), val
    if os.path.isfile(val):
        try:
            with open(val) as stream:
                val = yaml.safe_load(stream)
        except OSError as e:
            wandb.termwarn("Unable to read magic config file", repeat=False)
            return _magic_defaults, not_set
        except yaml.YAMLError as e:
            wandb.termwarn("Unable to parse magic yaml file", repeat=False)
            return _magic_defaults, not_set
        conf = _merge_dicts(_magic_defaults, {})
        return _merge_dicts(val, conf), val
    # parse as a list of key value pairs
    if val.find("=") > 0:
        # split on commas but ignore commas inside quotes
        # Using this re allows env variable parsing like:
        # WANDB_MAGIC=key1='"["cat","dog","pizza"]"',key2=true
        items = re.findall(r'(?:[^\s,"]|"(?:\\.|[^"])*")+', val)
        conf_set = {}
        for kv in items:
            kv = kv.split("=")
            if len(kv) != 2:
                wandb.termwarn("Unable to parse magic key value pair", repeat=False)
                continue
            d = _dict_from_keyval(*kv)
            _merge_dicts(d, conf_set)
        conf = _merge_dicts(_magic_defaults, {})
        return _merge_dicts(conf_set, conf), conf_set
    wandb.termwarn("Unable to parse magic parameter", repeat=False)
    return _magic_defaults, not_set


def set_entity(value, env=None):
    if env is None:
        env = os.environ


def _fit_wrapper(self, fn, generator=None, *args, **kwargs):
    trigger.call("on_fit")
    keras = sys.modules.get("keras", None)
    tfkeras = sys.modules.get("tensorflow.python.keras", None)
    epochs = kwargs.pop("epochs", None)
    batch_size = kwargs.pop("batch_size", None)

    magic_epochs = _magic_get_config("keras.fit.epochs", None)
    if magic_epochs is not None:
        epochs = magic_epochs
    magic_batch_size = _magic_get_config("keras.fit.batch_size", None)
    if magic_batch_size is not None:
        batch_size = magic_batch_size
    callbacks = kwargs.pop("callbacks", [])

    tb_enabled = _magic_get_config("keras.fit.callbacks.tensorboard.enable", None)
    if tb_enabled:
        k = getattr(self, "_keras_or_tfkeras", None)
        if k:
            tb_duplicate = _magic_get_config(
                "keras.fit.callbacks.tensorboard.duplicate", None
            )
            tb_overwrite = _magic_get_config(
                "keras.fit.callbacks.tensorboard.overwrite", None
            )
            tb_present = any(
                [isinstance(cb, k.callbacks.TensorBoard) for cb in callbacks]
            )
            if tb_present and tb_overwrite:
                callbacks = [
                    cb
                    for cb in callbacks
                    if not isinstance(cb, k.callbacks.TensorBoard)
                ]
            if tb_overwrite or tb_duplicate or not tb_present:
                tb_callback_kwargs = {"log_dir": wandb.run.dir}
                cb_args = (
                    "write_graph",
                    "histogram_freq",
                    "update_freq",
                    "write_grads",
                    "write_images",
                    "batch_size",
                )
                for cb_arg in cb_args:
                    v = _magic_get_config(
                        "keras.fit.callbacks.tensorboard." + cb_arg, None
                    )
                    if v is not None:
                        tb_callback_kwargs[cb_arg] = v
                tb_callback = k.callbacks.TensorBoard(**tb_callback_kwargs)
                callbacks.append(tb_callback)

    wandb_enabled = _magic_get_config("keras.fit.callbacks.wandb.enable", None)
    if wandb_enabled:
        wandb_duplicate = _magic_get_config("keras.fit.callbacks.wandb.duplicate", None)
        wandb_overwrite = _magic_get_config("keras.fit.callbacks.wandb.overwrite", None)
        wandb_present = any(
            [isinstance(cb, wandb.keras.WandbCallback) for cb in callbacks]
        )
        if wandb_present and wandb_overwrite:
            callbacks = [
                cb for cb in callbacks if not isinstance(cb, wandb.keras.WandbCallback)
            ]
        if wandb_overwrite or wandb_duplicate or not wandb_present:
            wandb_callback_kwargs = {}
            log_gradients = _magic_get_config(
                "keras.fit.callbacks.wandb.log_gradients", None
            )
            if log_gradients and kwargs.get("x") and kwargs.get("y"):
                wandb_callback_kwargs["log_gradients"] = log_gradients
            cb_args = (
                "predictions",
                "log_weights",
                "data_type",
                "save_model",
                "save_weights_only",
                "monitor",
                "mode",
                "verbose",
                "input_type",
                "output_type",
                "log_evaluation",
                "labels",
            )
            for cb_arg in cb_args:
                v = _magic_get_config("keras.fit.callbacks.wandb." + cb_arg, None)
                if v is not None:
                    wandb_callback_kwargs[cb_arg] = v
            wandb_callback = wandb.keras.WandbCallback(**wandb_callback_kwargs)
            callbacks.append(wandb_callback)

    kwargs["callbacks"] = callbacks
    if epochs is not None:
        kwargs["epochs"] = epochs
    if batch_size is not None:
        kwargs["batch_size"] = batch_size
    if generator:
        return fn(generator, *args, **kwargs)
    return fn(*args, **kwargs)


# NOTE(jhr): need to spell out all usable args so that users who inspect can see args
def _magic_fit(
    self,
    x=None,
    y=None,
    batch_size=None,
    epochs=1,
    # FIXME: there is more
    # verbose=1,
    # callbacks=None,
    # validation_split=0.,
    # validation_data=None,
    # shuffle=True,
    # class_weight=None,
    # sample_weight=None,
    # initial_epoch=0,
    # steps_per_epoch=None,
    # validation_steps=None,
    # validation_freq=1,
    # max_queue_size=10,
    # workers=1,
    # use_multiprocessing=False,
    *args,
    **kwargs,
):
    if hasattr(self, "_wandb_internal_model"):
        return self._fit(
            x=x, y=y, batch_size=batch_size, epochs=epochs, *args, **kwargs
        )
    return _fit_wrapper(
        self, self._fit, x=x, y=y, batch_size=batch_size, epochs=epochs, *args, **kwargs
    )


def _magic_fit_generator(
    self,
    generator,
    steps_per_epoch=None,
    epochs=1,
    # FIXME: there is more
    # verbose=1,
    # verbose=1,
    # callbacks=None,
    # validation_data=None,
    # validation_steps=None,
    # validation_freq=1,
    # class_weight=None,
    # max_queue_size=10,
    # workers=1,
    ##use_multiprocessing=False,
    # shuffle=True,
    # initial_epoch=0,
    *args,
    **kwargs,
):
    return _fit_wrapper(
        self,
        self._fit_generator,
        generator=generator,
        steps_per_epoch=steps_per_epoch,
        epochs=epochs,
        *args,
        **kwargs,
    )


def _monkey_tfkeras():
    from tensorflow import keras as tfkeras

    from wandb.integration.keras import WandbCallback  # add keras import hooks first

    models = getattr(tfkeras, "models", None)
    if not models:
        return
    models.Model._keras_or_tfkeras = tfkeras
    if models.Model.fit == _magic_fit:
        return
    models.Model._fit = models.Model.fit
    models.Model.fit = _magic_fit
    models.Model._fit_generator = models.Model.fit_generator
    models.Model.fit_generator = _magic_fit_generator


def _monkey_absl():
    from absl import app as absl_app

    def _absl_callback():
        absl_flags = sys.modules.get("absl.flags")
        if not absl_flags:
            return
        _flags = getattr(absl_flags, "FLAGS", None)
        if not _flags:
            return
        _flags_as_dict = getattr(_flags, "flag_values_dict", None)
        if not _flags_as_dict:
            return
        _flags_module = getattr(_flags, "find_module_defining_flag", None)
        if not _flags_module:
            return
        flags_dict = {}
        for f, v in _flags_as_dict().items():
            m = _flags_module(f)
            if not m or m.startswith("absl."):
                continue
            flags_dict[f] = v
        global _args_absl
        _args_absl = flags_dict

    call_after_init = getattr(absl_app, "call_after_init", None)
    if not call_after_init:
        return
    call_after_init(_absl_callback)


def _process_system_args():
    global _args_system
    # try using argparse
    parser = SafeArgumentParser(add_help=False)
    for num, arg in enumerate(sys.argv):
        try:
            next_arg = sys.argv[num + 1]
        except IndexError:
            next_arg = ""
        if arg.startswith(("-", "--")) and not next_arg.startswith(("-", "--")):
            try:
                parser.add_argument(arg)
            except ValueError:
                pass
    try:
        parsed, unknown = parser.parse_known_args()
    except ArgumentException:
        pass
    else:
        _args_system = vars(parsed)


def _monkey_argparse():
    argparse._ArgumentParser = argparse.ArgumentParser

    def _install():
        argparse.ArgumentParser = MonitoredArgumentParser

    def _uninstall():
        argparse.ArgumentParser = argparse._ArgumentParser

    def monitored(self, args, unknown=None):
        global _args_argparse
        _args_argparse = copy.deepcopy(vars(args))

    class MonitoredArgumentParser(argparse._ArgumentParser):
        def __init__(self, *args, **kwargs):
            _uninstall()
            super().__init__(*args, **kwargs)
            _install()

        def parse_args(self, *args, **kwargs):
            args = super().parse_args(*args, **kwargs)
            return args

        def parse_known_args(self, *args, **kwargs):
            args, unknown = super().parse_known_args(*args, **kwargs)
            if self._callback:
                self._callback(args, unknown=unknown)
            return args, unknown

    _install()
    argparse.ArgumentParser._callback = monitored


def _magic_update_config():
    # if we already have config set, don't add anymore
    if wandb.run and wandb.run.config:
        c = wandb.run.config
        user_config = dict(c.items())
        # ignore keys set by magic integration when checking
        # if user added any keys
        if set(user_config).difference({"magic"}):
            return
    if _magic_get_config("args.absl", None) is False:
        global _args_absl
        _args_absl = None
    if _magic_get_config("args.argparse", None) is False:
        global _args_argparse
        _args_argparse = None
    if _magic_get_config("args.sys", None) is False:
        global _args_system
        _args_system = None
    # prefer absl, then argparse values, fallback to parsed system args
    args = _args_absl or _args_argparse or _args_system
    if args and wandb.run and wandb.run.config:
        wandb.run.config.update(args)


def _magic_init(**kwargs):
    magic_arg = kwargs.get("magic", None)
    if magic_arg is not None and magic_arg is not False:
        global _magic_init_seen
        if _magic_init_seen and magic_arg is not True:
            wandb.termwarn(
                "wandb.init() magic argument ignored because wandb magic has already been initialized",
                repeat=False,
            )
        _magic_init_seen = True
    else:
        wandb.termwarn(
            "wandb.init() arguments ignored because wandb magic has already been initialized",
            repeat=False,
        )


def magic_install(init_args=None):
    if wandb.setup().settings._noop:
        return
    global _run_once
    if _run_once:
        return
    _run_once = True

    global _magic_config
    global _import_hook

    # parse config early, before we have wandb.config overrides
    _magic_config, magic_set = _parse_magic(wandb.env.get_magic())

    # we are implicitly enabling magic
    if _magic_config.get("enable") is None:
        _magic_config["enable"] = True
        magic_set["enable"] = True

    # allow early config to disable magic
    if not _magic_config.get("enable"):
        return

    # process system args
    _process_system_args()
    # install argparse wrapper
    in_jupyter_or_ipython = wandb.wandb_sdk.lib.ipython._get_python_type() != "python"
    if not in_jupyter_or_ipython:
        _monkey_argparse()

    # track init calls
    trigger.register("on_init", _magic_init)

    # if wandb.init has already been called, this call is ignored
    init_args = init_args or {}
    init_args["magic"] = True
    wandb.init(**init_args)

    # parse magic from wandb.config (from flattened to dict)
    magic_from_config = {}
    MAGIC_KEY = "wandb_magic"
    for k in wandb.config.keys():
        if not k.startswith(MAGIC_KEY + "."):
            continue
        d = _dict_from_keyval(k, wandb.config[k], json_parse=False)
        _merge_dicts(d, magic_from_config)
    magic_from_config = magic_from_config.get(MAGIC_KEY, {})
    _merge_dicts(magic_from_config, _magic_config)

    # allow late config to disable magic
    if not _magic_config.get("enable"):
        return

    # store magic_set into config
    if magic_set:
        wandb.config["magic"] = magic_set
        wandb.config.persist()

    # Monkey patch tf.keras
    if get_optional_module("tensorflow"):
        if "tensorflow.python.keras" in sys.modules or "keras" in sys.modules:
            _monkey_tfkeras()

    # Always setup import hooks looking for keras or tf.keras
    add_import_hook(fullname="keras", on_import=_monkey_tfkeras)
    add_import_hook(fullname="tensorflow.python.keras", on_import=_monkey_tfkeras)

    if "absl.app" in sys.modules:
        _monkey_absl()
    else:
        add_import_hook(fullname="absl.app", on_import=_monkey_absl)

    # update wandb.config on fit or program finish
    trigger.register("on_fit", _magic_update_config)
    trigger.register("on_finished", _magic_update_config)
