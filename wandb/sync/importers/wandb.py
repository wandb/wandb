from ..importer import AbstractRun, Importer
import wandb


class WandbRun(AbstractRun):
    def __init__(self, run):
        super(WandbRun, self).__init__()
        self.run = run

    def id(self):
        return self.run.id

    def notes(self):
        return self.run.notes

    def name(self):
        return self.run.name

    def config(self):
        return dict(self.run.config)

    def summary(self):
        return dict(self.run.summary)

    def start_time(self):
        return self.run.created_at

    def tags(self):
        return self.run.tags

    def program(self):
        # TODO: get program
        return None

    def git_url(self):
        # TODO: get gir
        return None

    def git_commit(self):
        return self.run.commit

    def tensorboard_logdir(self):
        return None

    def finish_time(self):
        return self.run.finished_at

    def job_type(self):
        return self.run.job_type

    def group(self):
        return self.run.group

    def metrics(self):
        # TODO: full history, make this an iterator
        return self.run.history(pandas=False)


class WandbImporter(Importer):
    """Usage:
        WandbImporter("https://wandb.ai/username/project", "https://local.wandb.ai/username/project",
    {"state": "finished", "created_at": {"$gt": "06/06/2011"}})
    """

    def __init__(self, source, destination, filters={}):
        # TODO: handle full urls
        entity, project = destination.split("/")
        super(WandbImporter, self).__init__(entity, project)
        self.api = wandb.Api()
        self.runs = self.api.runs(source, filters=filters)

    def process(self):
        for run in self.runs:
            self.add(WandbRun(run))
        super(WandbImporter, self).process()
