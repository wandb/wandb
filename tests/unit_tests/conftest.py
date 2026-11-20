import unittest.mock
from collections.abc import Callable, Generator
from datetime import timedelta
from queue import Queue

import pytest
import wandb
from hypothesis import settings
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface import InterfaceBase

settings.register_profile(
    "ci",
    max_examples=10,
    deadline=timedelta(seconds=1),
)
settings.load_profile("ci")


@pytest.fixture
def api() -> wandb.Api:
    """A fake wandb.Api instance.

    Unit tests can't talk to a local-testcontainer, so most methods on this
    will fail unless patched.
    """
    with unittest.mock.patch("wandb.sdk.wandb_login._verify_login"):
        return wandb.Api()


@pytest.fixture
def deliver_upload_eval_table(monkeypatch) -> unittest.mock.MagicMock:
    """The mocked `InterfaceBase.deliver_upload_eval_table`.

    By default, every upload succeeds with fixed evaluation and dataset IDs.
    """
    deliver = unittest.mock.MagicMock()
    deliver.return_value.wait_or.return_value = pb.Result(
        response=pb.Response(
            upload_eval_table_response=pb.UploadEvalTableResponse(
                evaluation_id="evaluation-1",
                evaluation_version_id="evaluation-version-1",
                dataset_id="dataset-1",
                dataset_version_id="dataset-version-1",
            )
        )
    )
    monkeypatch.setattr(InterfaceBase, "deliver_upload_eval_table", deliver)
    return deliver


# --------------------------------
# Fixtures for user test point
# --------------------------------


class RecordsUtil:
    def __init__(self, queue: Queue) -> None:
        self.records = []
        while not queue.empty():
            self.records.append(queue.get())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, name: str) -> Generator:
        for record in self.records:
            yield from self.resolve_item(record, name)

    @staticmethod
    def resolve_item(obj, attr: str, sep: str = ".") -> list:
        for name in attr.split(sep):
            if not obj.HasField(name):
                return []
            obj = getattr(obj, name)
        return [obj]

    @staticmethod
    def dictify(obj, key: str = "key", value: str = "value_json") -> dict:
        return {getattr(item, key): getattr(item, value) for item in obj}

    @property
    def config(self) -> list:
        return [self.dictify(_c.update) for _c in self["config"]]

    @property
    def history(self) -> list:
        return [self.dictify(_h.item) for _h in self["history"]]

    @property
    def partial_history(self) -> list:
        return [self.dictify(_h.item) for _h in self["request.partial_history"]]

    @property
    def preempting(self) -> list:
        return list(self["preempting"])

    @property
    def summary(self) -> list:
        return list(self["summary"])

    @property
    def files(self) -> list:
        return list(self["files"])

    @property
    def metric(self):
        return list(self["metric"])


@pytest.fixture
def parse_records() -> Generator[Callable, None, None]:
    def records_parser_fn(q: Queue) -> RecordsUtil:
        return RecordsUtil(q)

    yield records_parser_fn
