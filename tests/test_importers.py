import wandb
from datetime import datetime
from wandb.importers import AbstractRun, Importer, WandbImporter


class MockedRun(AbstractRun):
    def __init__(self):
        super(MockedRun, self).__init__()

    def id(self):
        return wandb.util.generate_id()

    def name(self):
        return "Mocked run"

    def config(self):
        return {"learning_rate": 1}

    def summary(self):
        return {"accuracy": 0.5}

    def start_time(self):
        return datetime.now()

    def tags(self):
        return ["prod"]

    def program(self):
        return "train.py"

    def git_url(self):
        return "git://github.com/wandb/client.git"

    def git_commit(self):
        return "ba49fa1d3927e6e5a070bad7f64068b9455a476b"

    def tensorboard_logdir(self):
        return None

    def finish_time(self):
        return datetime.now()

    def job_type(self):
        return "test"

    def group(self):
        return "experiment_1"

    def metrics(self):
        for i in range(10):
            yield {"metric": i}


def test_base_importer(mock_server, parse_ctx):
    importer = Importer("test", "test")
    for _ in range(5):
        importer.add(AbstractRun())
    importer.process()
    ctx_util = parse_ctx(mock_server.ctx)
    assert ctx_util.summary == {}
    assert len(ctx_util.run_ids) == 5
    assert ctx_util.history is None


def test_generic_importer(mock_server, parse_ctx):
    importer = Importer("test", "test")
    for _ in range(5):
        importer.add(MockedRun())
    importer.process()
    ctx_util = parse_ctx(mock_server.ctx)
    assert ctx_util.summary == {"accuracy": 0.5}
    assert len(ctx_util.run_ids) == 5
    assert len(ctx_util.history) == 10


def test_wandb_importer(mock_server, parse_ctx, runner):
    mock_server.set_context("page_times", 4)
    importer = WandbImporter("foo/bar", "test/test")
    importer.process()
    ctx_util = parse_ctx(mock_server.ctx)
    assert ctx_util.summary == {"acc": 100, "loss": 0}
    assert len(ctx_util.run_ids) == 4
    assert len(ctx_util.history) == 3
