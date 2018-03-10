import os
import yaml
import json
import re
import glob
import socket
import getpass
import hashlib
import logging
from six.moves import urllib
from datetime import datetime
from dateutil.parser import parse


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
            datetime.utcnow()

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


class Log(Base):
    def __init__(self, base_path):
        super(Log, self).__init__(base_path)
        self.name = "output.log"

    def lines(self):
        from wandb.board.app.graphql.schema import LogLine
        lines = []
        for i, line in enumerate(self.read().split("\n")):
            lines.append(LogLine(
                line=line,
                number=i,
                id=i,
                level="error" if line.startswith("ERROR") else "info"
            ))
        return lines


class Meta(Summary):
    def __init__(self, base_path):
        super(Meta, self).__init__(base_path)
        self.name = "wandb-metadata.json"


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
        self.load_meta()

    @property
    def created_at(self):
        startedAt = self.meta.get("startedAt") and parse(
            self.meta["startedAt"])
        return startedAt or datetime.strptime(self.date, "%Y%m%d_%H%M%S")

    @property
    def heartbeat_at(self):
        if self.meta.get("heartbeatAt"):
            return parse(self.meta["heartbeatAt"])
        latest = None
        for path in glob.glob("%s/*" % self.path):
            mtime = datetime.utcfromtimestamp(
                os.path.getmtime(path))
            if not latest or latest < mtime:
                latest = mtime
        return latest

    def load_meta(self):
        self.meta = Meta(self.path).parsed()
        if not self.meta.get("git"):
            self.meta["git"] = {}

    def gravatar(self):
        default = "/unknown.jpeg"
        size = 40
        if self.meta.get("email"):
            gravatar_url = "https://www.gravatar.com/avatar/" + \
                hashlib.md5(self.meta["email"].lower().encode(
                    "utf8")).hexdigest() + "?"
            gravatar_url += urllib.parse.urlencode(
                {'d': default, 's': str(size)})
            return gravatar_url
        else:
            return default

    def load(self, run=None):
        from wandb.board.app.graphql.schema import Run, UserType
        if not run:
            run = Run()
        self.load_meta()
        desc = Description(self.path)
        config = Config(self.path)
        summary = Summary(self.path)
        patch = Patch(self.path)
        run.path = self.path
        run.id = self.run_id
        run.createdAt = self.created_at.isoformat()
        run.heartbeatAt = self.updated_at.isoformat()
        run.description = desc.read()
        run.commit = self.meta["git"].get("commit")
        run.state = self.meta.get("state", "finished")
        age = (datetime.utcnow() - self.updated_at).total_seconds()
        if run.state == "running" and age > 300:
            run.state = "crashed"
        run.host = self.meta.get("host", socket.gethostname())
        run.patch = patch.read()
        run.summaryMetrics = summary.parsed()
        run.config = config.parsed()
        run.user = UserType(
            email=self.meta.get("email"),
            username=self.meta.get("username", getpass.getuser()),
            photoUrl=self.gravatar()
        )
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
