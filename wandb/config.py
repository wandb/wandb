import yaml, os, sys, logging
from .api import Error

def boolify(s):
    if s.lower() == 'none':
        return None
    if s.lower() == 'true':
        return True
    if s.lower() == 'false':
        return False
    raise ValueError("Not a boolean")

class Config(dict):
    """Creates a W&B config object.

    The object is an enhanced `dict`.  You can access keys via instance methods or
    as you would a regular `dict`.  The object first looks for a `config.yaml` file
    in the current directory.  It then looks for environment variables pre-pended
    with "WANDB_".  Lastly it overrides any key found in command line arguments.

    Using the config objects enables W&B to track all configuration parameters used
    in your training runs.

    Args:
        config(:obj:`dict`, optional): Key value pairs from your existing code that
        you would like to track.  You can also pass in objects that respond to `__dict__`
        such as from argparse.
    """
    def __init__(self, config={}):
        if not isinstance(config, dict):
            try:
                # for tensorflow flags
                if "__flags" in dir(config):
                    if not config.__parsed:
                        config._parse_flags()
                    config = config.__flags
                else:
                    config = vars(config)
            except TypeError:
                raise TypeError("config must be a dict or have a __dict__ attribute.")
        dict.__init__(self, {})
        self._descriptions = {}
        # we only persist when _external is True
        self._external = False
        self.load_defaults()
        self.load_env()
        self.load_overrides()
        for key in config:
            self[key] = config[key]
        self._external = True
        self.persist(overrides=True)

    @property
    def config_dir(self):
        """The config directory holding the latest configuration"""
        return os.getcwd() + "/.wandb"

    @property
    def defaults_path(self):
        """Where to find the default configuration"""
        return os.getcwd() + "/config.yaml"

    @property
    def keys(self):
        """All keys in the current configuration"""
        return [key for key in self if not key.startswith("_")]

    def desc(self, key):
        """The description of a given key"""
        return self._descriptions.get(key)

    def convert(self, ob):
        """Type casting for Boolean, None, Int and Float"""
        #TODO: deeper type casting
        if isinstance(ob, dict) or isinstance(ob, list):
            return ob
        for fn in (boolify, int, float):
            try:
                return fn(str(ob))
            except ValueError:
                pass
        return str(ob)

    def load_defaults(self):
        """Load defaults from YAML"""
        if os.path.exists(self.defaults_path):
            try:
                defaults = yaml.load(open(self.defaults_path))
            except yaml.parser.ParserError:
                raise Error("Invalid YAML in config.yaml")
            if defaults:
                for key in defaults:
                    if key == "wandb_version":
                        continue
                    self[key] = defaults[key].get('value')
                    self._descriptions[key] = defaults[key].get('desc')
        else:
            logging.info("Couldn't load default config, run `wandb config init` in this directory")

    def load_overrides(self):
        """Load overrides from command line arguments"""
        for arg in sys.argv:
            key_value = arg.split("=")
            if len(key_value) == 2:
                key = key_value[0].replace("--", "")
                if self.get(key):
                    self[key] = self.convert(key_value[1])

    def load_env(self):
        """Load overrides from the environment"""
        for key in [key for key in os.environ if key.startswith("WANDB")]:
            value = os.environ[key]
            self[key.replace("WANDB_", "").lower()] = self.convert(value)

    def persist(self, overrides=False):
        """Stores the current configuration for pushing to W&B"""
        if overrides:
            path = "{dir}/latest.yaml".format(dir=self.config_dir)
        else:
            path = self.defaults_path
        try:
            with open(path, "w") as defaults_file:
                defaults_file.write(str(self))
            return True
        except IOError:
            logging.warn("Unable to persist config, no .wandb directory exists.  Run `wandb config init` in this directory.")
            return False

    def __getitem__(self, name):
        return super(Config, self).__getitem__(name)

    def __setitem__(self, key, value):
        #TODO: this feels gross
        if key.endswith("_desc"):
            parts = key.split("_")
            parts.pop()
            self._descriptions["_".join(parts)] = str(value)
        else:
            #TODO: maybe don't convert, but otherwise python3 dumps unicode
            super(Config, self).__setitem__(key, self.convert(value))
            if not key.startswith("_") and self._external:
                self.persist(overrides=True)
            return value

    def __getattr__(self, name):
        return self.get(name)

    __setattr__ = __setitem__

    @property
    def __dict__(self):
        defaults = {}
        for key in self.keys:
            defaults[key] = {'value':self[key], 'desc':self._descriptions.get(key)}
        return defaults

    def __repr__(self):
        rep = "\n".join([str({
            'key': key,
            'desc': self._descriptions.get(key),
            'value': self[key]
        }) for key in self.keys])
        return rep

    def __str__(self):
        return "wandb_version: 1\n\n"+yaml.dump(self.__dict__, default_flow_style=False)
