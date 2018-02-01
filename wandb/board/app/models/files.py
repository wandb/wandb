import os
import yaml
import json
import re
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

    def mutate(self, value):
        with open(self.file_name, "w") as f:
            f.write(value)


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
        except ValueError:
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
        matches = re.search(
            r'.*wandb/(dry)?run-(\d{8}_\d{6})-(\w{8})', base_path)
        if matches is None:
            raise ValueError("Invalid directory: %s" % base_path)
        self.date = matches.group(2)
        self.run_id = matches.group(3)
        path = base_path.split(self.run_id)[0] + self.run_id
        super(Dir, self).__init__(path)

    @property
    def created_at(self):
        return datetime.strptime(self.date, "%Y%m%d_%H%M%S")

    @property
    def heartbeat_at(self):
        return Summary(self.path).updated_at

    def load(self, run=None):
        from wandb.board.app.graphql.schema import Run
        if not run:
            run = Run()
        desc = Description(self.path)
        config = Config(self.path)
        summary = Summary(self.path)
        patch = Patch(self.path)
        run.path = self.path
        run.id = self.run_id
        run.createdAt = self.created_at
        run.heartbeatAt = summary.updated_at
        run.description = desc.read()
        run.state = "finished"
        run.patch = patch.read()
        run.summaryMetrics = summary.parsed()
        run.config = config.parsed()
        return run


class Settings(Base):
    def __init__(self, base_path, project="default"):
        super(Settings, self).__init__(base_path)
        self.name = "board-settings.json"
        self.project = project
        self.data = self.parsed()

    def set_project(self, key, value):
        self.data["projects"][self.project][key] = value

    def get_project(self, key=None):
        if key:
            return self.data["projects"][self.project].get(key)
        else:
            return self.data["projects"][self.project]

    def save(self):
        with open(self.file_name, "w") as settings:
            settings.write(json.dumps(self.data))

    def parsed(self):
        try:
            return json.loads(self.read())
        except ValueError:
            return {"projects": {"default": {}}}


class RunMutator(Base):
    def __init__(self, run):
        super(RunMutator, self).__init__(run.path)
        self.run = run

    def __setattr__(self, name, value):
        if name == 'description':
            self.run.description = value
            Description(self.path).mutate(value)
        else:
            super(RunMutator, self).__setattr__(name, value)
