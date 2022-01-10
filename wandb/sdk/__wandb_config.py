#
"""
config.
"""

import logging
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

import wandb
from wandb.util import check_dict_contains_nested_artifact, json_friendly_val

from . import wandb_helper
from .lib import config_util


logger = logging.getLogger("wandb")

if TYPE_CHECKING:
    from wandb.sdk.wandb_settings import Settings


class Property:
    def __init__(
        self,
        name: str,
        value: Optional[Any],
        lock: Optional[str] = None,
        **kwargs,
    ) -> None:
        self._name = name
        self._value = value
        self._lock = lock

    @property
    def _is_locked(self) -> bool:
        return self._lock is not None

    def lock(self, lock: str) -> None:
        self._lock = lock

    def update(
        self,
        value: Any,
        lock: Optional[str] = None,
        ignore_locked: bool = False,
        allow_override: bool = False,
    ) -> Optional["Property"]:

        update_lock = lock is not None
        if self._is_locked and not (ignore_locked or update_lock):
            wandb.termwarn(
                f"Config item {self._name} was locked by {self._lock} (ignored update)."
            )
            return

        if value != self._value and not allow_override:
            raise config_util.ConfigError(
                (
                    f"Attempted to change the value of key '{self._name}' from {self._value} to {value}\n"
                    "To force the change, pass `allow_val_change=True` in `config.update()`"
                )
            )

        self._value = value
        if update_lock:
            self.lock(lock)
        return self


class Config:
    def __init__(
        self,
        callback: Optional[Callable] = None,
        settings: Optional["Settings"] = None,
    ):
        object.__setattr__(self, "_callback", callback)
        object.__setattr__(self, "_settings", settings)

        object.__setattr__(self, "_data", {})

        # Load defaults
        config = config_util.dict_from_config_file("config-defaults.yaml")
        if config is not None:
            self.update(config)

    @staticmethod
    def _sanitize(_name: str, _value: Any) -> Tuple[str, Any]:
        # We always normalize keys by stripping '-'
        key = _name.strip("-")

        value = _value
        # if the user inserts an artifact into the config
        if not isinstance(value, (wandb.Artifact, wandb.apis.public.Artifact)):
            value = json_friendly_val(value)
        return key, value

    @staticmethod
    def _raise_value_error_on_nested_artifact(
        _value: Any, nested: bool = False
    ) -> None:
        # we can't swap nested artifacts because their root key can be locked by other values
        # best if we don't allow nested artifacts until we can lock nested keys in the config
        if isinstance(_value, dict) and check_dict_contains_nested_artifact(
            _value, nested
        ):
            raise ValueError(
                "Instances of wandb.Artifact and wandb.apis.public.Artifact"
                " can only be top level keys in wandb.config"
            )

    # def _set_callback(self, cb):
    #     object.__setattr__(self, "_callback", cb)

    # def _set_settings(self, settings):
    #     object.__setattr__(self, "_settings", settings)

    def _update_item(
        self,
        _name: str,
        _value: Any,
        _lock: Optional[str] = None,
        ignore_locked: bool = False,
        allow_override: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        # Let jupyter change config freely by default
        if self._settings and self._settings._jupyter and allow_override is None:
            allow_override = True

        key, value = self._sanitize(_name, _value)

        if key not in self._data:
            value = Property(name=key, value=value, lock=_lock)
            self._data[key] = value
        else:
            value = self._data[key].update(value, _lock, ignore_locked, allow_override)

        return value

    def __setitem__(self, _name: str, _value: Any) -> None:

        # self._raise_value_error_on_nested_artifact(_value, nested=True)

        result = self._update_item(_name, _value)
        breakpoint()
        with wandb.sdk.lib.telemetry.context() as tel:
            tel.feature.set_config_item = True
        if self._callback and result is not None:
            result = {"key": result._name, "val": result._value}
            logger.info(f"Config set {result} - and calls callback: {self._callback}")
            self._callback(**result)

    __setattr__ = __setitem__

    def __getitem__(self, _name: str) -> Any:
        return self._data[_name]._value

    def __getattr__(self, _name: str) -> Any:
        return self.__getitem__(_name)

    def __contains__(self, _name: str) -> bool:
        return _name in self._data

    def __repr__(self):
        return str(dict(self))

    def _update(
        self,
        config: Any,
        allow_val_change: Optional[bool] = None,
        ignore_locked: Optional[bool] = None,
    ) -> Dict[str, Any]:

        config = wandb_helper.parse_config(config)
        self._raise_value_error_on_nested_artifact(config)

        data = {}
        for key, value in config.items():
            result = self._update_item(
                key,
                value,
                ignore_locked=ignore_locked,
                allow_override=allow_val_change,
            )
            if result is not None:
                data.update({result._name: result._value})

        return data

    def update(self, config: Any, allow_val_change: Optional[bool] = None) -> None:

        data = self._update(config, allow_val_change=allow_val_change)
        if self._callback:
            self._callback(data=data)

    def update_locked(
        self,
        config: Any,
        user: Optional[str] = None,
        allow_val_change: Optional[bool] = None,
    ) -> None:

        config = wandb_helper.parse_config(config)

        data = {}
        for key, value in config.items():
            result = self._update_item(
                key, value, _lock=user, allow_override=allow_val_change
            )
            if result is not None:
                data.update({result._name: result._value})

        if self._callback:
            self._callback(data=data)

    def setdefaults(self, config: Any) -> None:
        config = wandb_helper.parse_config(config)
        config = {k: v for k, v in config.items() if k not in self._data}

        self._raise_value_error_on_nested_artifact(config)

        data = {}
        for key, value in config.items():
            result = self._update_item(key, value)
            if result is not None:
                data.update({result._name: result._value})

        if self._callback:
            self._callback(data=data)

    def keys(self):
        return [k for k in self._data.keys() if not k.startswith("_")]

    def items(self):
        return [(k, v) for k, v in self._data.items() if not k.startswith("_")]

    def _as_dict(self):
        return {k: v._value for k, v in self._data.items()}

    def as_dict(self):
        # TODO: add telemetry, deprecate, then remove
        return dict(self)

    def get(self, *args):
        return self._data.get(*args)

    def persist(self):
        """Calls the callback if it's set"""
        if self._callback:
            self._callback(data=self._as_dict())


class ConfigStatic:
    def __init__(self, config):
        object.__setattr__(self, "__dict__", dict(config))

    def __setattr__(self, name, value):
        raise AttributeError("Error: wandb.run.config_static is a readonly object")

    def __setitem__(self, key, val):
        raise AttributeError("Error: wandb.run.config_static is a readonly object")

    def keys(self):
        return self.__dict__.keys()

    def __getitem__(self, key):
        return self.__dict__[key]

    def __str__(self):
        return str(self.__dict__)
