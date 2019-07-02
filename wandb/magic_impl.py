from __future__ import absolute_import

import sys
import six
import argparse
import copy
import json
import os
import yaml
import importlib

import wandb
from wandb import trigger


_import_hook = None
_run_once = False
_args_argparse = None
_args_system = None
_magic_init_seen = False
_magic_config = {}


# PEP302 new import hooks, in python3 we could use importlib
class ImportMetaHook():
    def __init__(self, watch=(), on_import=None):
        if isinstance(watch, six.string_types):
            watch = tuple([watch])
        self.watch_items = frozenset(watch)
        self.modules = {}
        self.on_import = on_import

    def install(self):
        sys.meta_path.insert(0, self)

    def uninstall(self):
        sys.meta_path.remove(self)

    def find_module(self, fullname, path=None):
        lastname = fullname.split('.')[-1]
        if lastname in self.watch_items:
            return self

    def load_module(self, fullname):
        self.uninstall()
        mod = importlib.import_module(fullname)
        self.install()
        self.modules[fullname] = mod
        if self.on_import:
            self.on_import(fullname)
        return mod

    def get_modules(self):
        return tuple(self.modules)

    def get_module(self, module):
        return self.modules[module]


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


def _dict_from_keyval(k, v):
    d = ret = {}
    keys = k.split('.')
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    try:
        v = json.loads(v)
    except ValueError:
        pass
    d[keys[-1]] = v
    return ret


def _magic_get_config(k, default):
    d = _magic_config
    keys = k.split('.')
    for k in keys[:-1]:
        d = d.get(k, {})
    return d.get(keys[-1], default)


_magic_defaults = {
    'magic': {
        'keras': {
            'fit': {
                'callbacks': {
                    'tensorboard': {
                        'enable': True
                        },
                    'wandb': {
                        'enable': True
                        }
                    }
                }
            }
        }
    }
            

def _parse_magic(val):
    # attempt to treat string as a json
    if val is None:
        return _magic_defaults
    if val.startswith("{"):
        try:
            val = json.loads(val)
        except ValueError:
            wandb.termwarn("Unable to parse magic json", repeat=False)
            return _magic_defaults
        return _merge_dicts(_magic_defaults, val)
    if os.path.isfile(val):
        try:
            with open(val, 'r') as stream:
                val = yaml.safe_load(stream)
        except IOError as e:
            wandb.termwarn("Unable to read magic config file", repeat=False)
            return _magic_defaults
        except yaml.YAMLError as e:
            wandb.termwarn("Unable to parse magic yaml file", repeat=False)
            return _magic_defaults
        return _merge_dicts(_magic_defaults, val)
    # parse as a list of key value pairs
    if val.find('=') > 0:
        conf = {}
        _merge_dicts(_magic_defaults, conf)
        for kv in val.split(','):
            kv = kv.split('=')
            if len(kv) != 2:
                wandb.termwarn("Unable to parse magic key value pair", repeat=False)
                continue
            d = _dict_from_keyval(*kv)
            _merge_dicts(d, conf)
        return conf
    wandb.termwarn("Unable to parse magic parameter", repeat=False)
    return _magic_defaults
        

def set_entity(value, env=None):
    if env is None:
        env = os.environ


def _fit_wrapper(fn, generator=None, *args, **kwargs):
    trigger.call('on_fit')
    keras = sys.modules.get("keras", None)
    tfkeras = sys.modules.get("tensorflow.python.keras", None)
    epochs = kwargs.pop("epochs", None)

    magic_epochs = _magic_get_config("magic.keras.fit.epochs", None)
    if magic_epochs is not None:
        epochs = magic_epochs
    callbacks = kwargs.pop("callbacks", [])

    tb_enabled = _magic_get_config("magic.keras.fit.callbacks.tensorboard.enable", None)
    if tb_enabled:
        k = tfkeras or keras
        if k and not any([isinstance(cb, k.callbacks.TensorBoard) for cb in callbacks]):
            tb_callback = k.callbacks.TensorBoard(log_dir=wandb.run.dir)
            callbacks.append(tb_callback)
    
    wandb_enabled = _magic_get_config("magic.keras.fit.callbacks.wandb.enable", None)
    if wandb_enabled:
        if not any([isinstance(cb, wandb.keras.WandbCallback) for cb in callbacks]):
            wandb_callback = wandb.keras.WandbCallback()
            callbacks.append(wandb_callback)

    kwargs["callbacks"] = callbacks
    if epochs is not None:
        kwargs["epochs"] = epochs
    if generator:
        return fn(generator, *args, **kwargs)
    return fn(*args, **kwargs)


# NOTE(jhr): need to spell out all useable args so that users who inspect can see args
def _magic_fit(self,
        x=None,
        y=None,
        batch_size=None,
        epochs=1,
        # FIXME: there is more
        #verbose=1,
        #callbacks=None,
        #validation_split=0.,
        #validation_data=None,
        #shuffle=True,
        #class_weight=None,
        #sample_weight=None,
        #initial_epoch=0,
        #steps_per_epoch=None,
        #validation_steps=None,
        #validation_freq=1,
        #max_queue_size=10,
        #workers=1,
        #use_multiprocessing=False,
        *args, **kwargs):
    return _fit_wrapper(self._fit, x=x, y=y, batch_size=batch_size, epochs=epochs, *args, **kwargs)


def _magic_fit_generator(self, generator,
                    steps_per_epoch=None,
                    epochs=1,
                    # FIXME: there is more
                    #verbose=1,
                    #verbose=1,
                    #callbacks=None,
                    #validation_data=None,
                    #validation_steps=None,
                    #validation_freq=1,
                    #class_weight=None,
                    #max_queue_size=10,
                    #workers=1,
                    ##use_multiprocessing=False,
                    #shuffle=True,
                    #initial_epoch=0,
                    *args, **kwargs):
    return _fit_wrapper(self._fit_generator, generator=generator, steps_per_epoch=steps_per_epoch, epochs=epochs, *args, **kwargs)


def _monkey_keras(keras):
    models = getattr(tfkeras, 'engine', None)
    if not models:
        return
    models.Model._fit = models.Model.fit
    models.Model.fit = _magic_fit
    models.Model._fit_generator = models.Model.fit_generator
    models.Model.fit_generator = _magic_fit_generator


def _monkey_tfkeras(tfkeras):
    models = getattr(tfkeras, 'models', None)
    if not models:
        return
    models.Model._fit = models.Model.fit
    models.Model.fit = _magic_fit
    models.Model._fit_generator = models.Model.fit_generator
    models.Model.fit_generator = _magic_fit_generator


def _on_import_keras(fullname):
    if fullname == 'keras':
        keras = _import_hook.get_module('keras')
        _monkey_keras(keras)
    if fullname == 'tensorflow.python.keras':
        keras = _import_hook.get_module('tensorflow.python.keras')
        _monkey_tfkeras(keras)


def _process_system_args():
    global _args_system
    # try using argparse
    parser=SafeArgumentParser(add_help=False)
    for num, arg in enumerate(sys.argv):
        try:
            next_arg = sys.argv[num + 1]
        except IndexError:
            next_arg = ''
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
            super(MonitoredArgumentParser, self).__init__(*args, **kwargs)
            _install()

        def parse_args(self, *args, **kwargs):
            args = super(MonitoredArgumentParser, self).parse_args(*args, **kwargs)
            return args

        def parse_known_args(self, *args, **kwargs):
            args, unknown = super(MonitoredArgumentParser, self).parse_known_args(*args, **kwargs)
            if self._callback:
                self._callback(args, unknown=unknown)
            return args, unknown

    _install()
    argparse.ArgumentParser._callback = monitored
    

def _magic_update_config():
    # if we already have config set, dont add anymore
    if wandb.run and wandb.run.config:
        c = wandb.run.config
        user_config = dict(c.user_items())
        if user_config:
            return
    # prefer argparse values, fallback to parsed system args
    args = _args_argparse or _args_system
    if args and wandb.run and wandb.run.config:
        wandb.run.config.update(args)


def _magic_init(**kwargs):
    magic_arg = kwargs.get("magic", None)
    if magic_arg is not None and magic_arg is not False:
        global _magic_init_seen
        if _magic_init_seen and magic_arg is not True:
            wandb.termwarn("wandb.init() magic argument ignored because wandb magic has already been initialized", repeat=False)
        _magic_init_seen = True
    else:
        wandb.termwarn("wandb.init() arguments ignored because wandb magic has already been initialized", repeat=False)


def magic_install():
    global _run_once
    if _run_once:
        return
    _run_once = True

    # process system args
    _process_system_args()
    # install argparse wrapper
    _monkey_argparse()

    # track init calls
    trigger.register('on_init', _magic_init)

    wandb.init(magic=True)
    global _magic_config
    _magic_config = _parse_magic(wandb.env.get_magic())

    if 'tensorflow.python.keras' in sys.modules:
        _monkey_tfkeras(sys.modules.get('tensorflow.python.keras'))
    elif 'keras' in sys.modules:
        _monkey_keras(sys.modules.get('keras'))
    else:
        global _import_hook
        _import_hook = ImportMetaHook(watch='keras', on_import=_on_import_keras)
        _import_hook.install()

    # update wandb.config on fit or program finish
    trigger.register('on_fit', _magic_update_config)
    trigger.register('on_finished', _magic_update_config)
