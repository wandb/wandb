"""Base SweepConfig classes.
"""

import wandb
import yaml

from six.moves import UserDict


class SweepConfig(UserDict):
    def __init__(self, d):
        super(SweepConfig, self).__init__(d)

    def __str__(self):
        return yaml.safe_dump(self.data)

    def save(self, filename):
        with open(filename, "w") as outfile:
            yaml.safe_dump(self.data, outfile, default_flow_style=False)

    def set_local(self):
        self.data.update(dict(controller=dict(type="local")))
        return self

    def set_name(self, name):
        self.data.update(dict(name=name))
        return self

    def set_settings(self, settings):
        self.data.update(dict(settings=settings))
        return self

    def set(self, **kwargs):
        local = kwargs.pop("local", None)
        name = kwargs.pop("name", None)
        settings = kwargs.pop("settings", None)
        if local:
            self.set_local()
        if name:
            self.set_name(name)
        if name:
            self.set_settings(settings)
        for k in kwargs.keys():
            wandb.termwarn("Unsupported parameter passed to SweepConfig set(): {}".format(k))
        return self


class SweepConfigElement:
    _version_dict = {}
    def __init__(self, module=None, version=None):
        self._module = module
        self._version = version
        self._version_dict.setdefault("wandb", wandb.__version__)
        if module and version:
            self._version_dict.setdefault(module, version)

    def _config(self, base, args, kwargs, root=False):
        kwargs = {k:v for k, v in kwargs.items() if v is not None and k is not "self"}
        # remove kwargs if empty
        if kwargs.get("kwargs") == {}:
            del kwargs["kwargs"]
        # if only kwargs specified and only two keys "args" and "kargs"
        special = not args and set(kwargs.keys()) == set(("args", "kwargs"))
        if args and kwargs or special:
            d = dict(args=args, kwargs=kwargs)
        elif args:
            d = args
        else:
            d = kwargs
        if base:
            if self._module:
                base = self._module + "." + base
            d = {base: d}
        if root:
            # HACK(jhr): move tune.run to tune
            d = d["tune.run"]
            d = dict(tune=d)
            for m, v in self._version_dict.items():
                d["tune"].setdefault("_wandb", {})
                d["tune"]["_wandb"].setdefault("versions", {})
                d["tune"]["_wandb"]["versions"][m] = v
            return SweepConfig(d)
        return d
