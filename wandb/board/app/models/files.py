import os
import yaml
import json
from datetime import datetime


class Base(object):
    def __init__(self, base_path):
        self.path = base_path
        self.name = "."

    @property
    def file_name(self, name=None):
        return os.path.join(self.path, name or self.name)

    @property
    def exists(self):
        return os.path.exists(self.file_name)

    @property
    def updated_at(self):
        if self.exists:
            return datetime.utcfromtimestamp(
                os.path.getmtime(self.file_name))
        else:
            datetime.now()

    def read(self):
        if self.exists:
            with open(self.file_name) as f:
                return f.read()
        else:
            return ""


class Description(Base):
    def __init__(self, base_path):
        super(Description, self).__init__(base_path)
        self.name = "description.md"


class Patch(Base):
    def __init__(self, base_path):
        super(Patch, self).__init__(base_path)
        self.name = "diff.patch"


class Config(Base):
    def __init__(self, base_path):
        super(Config, self).__init__(base_path)
        self.name = "config.yaml"

    def parsed(self):
        try:
            return yaml.load(self.read())
        except yaml.YAMLError:
            return {}


class Summary(Base):
    def __init__(self, base_path):
        super(Summary, self).__init__(base_path)
        self.name = "wandb-summary.json"

    def parsed(self):
        try:
            return json.loads(self.read())
        except json.decoder.JSONDecodeError:
            return {}


class History(Base):
    def __init__(self, base_path):
        super(History, self).__init__(base_path)
        self.name = "wandb-history.jsonl"


class Events(Base):
    def __init__(self, base_path):
        super(Events, self).__init__(base_path)
        self.name = "wandb-events.jsonl"


class Dir(Base):
    def __init__(self, base_path):
        super(Dir, self).__init__(base_path)
        _, self.date, self.run_id = self.path.split("wandb")[-1].split("-")

    @property
    def created_at(self):
        return datetime.strptime(self.date, "%Y%m%d_%H%M%S")

    @property
    def heartbeat_at(self):
        return Summary(self.path).updated_at
