import unittest.mock
from collections.abc import Generator
from datetime import timedelta
from queue import Queue
from typing import Callable

import pytest
import wandb
from hypothesis import settings
from wandb.sdk import wandb_setup

settings.register_profile(
    "ci",
    max_examples=10,
    deadline=timedelta(seconds=1),
)
settings.load_profile("ci")


_UNIT_TEST_BASE_URL = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def unit_test_fake_base_url(monkeypatch: pytest.MonkeyPatch, clean_up) -> None:
    """Point unit tests at a fail-fast dead URL unless they override it.

    This catches accidental network dependencies in unit tests while still
    allowing individual tests to opt into a different base URL with their own
    monkeypatching or fixtures.
    """
    _ = clean_up

    monkeypatch.setenv("WANDB_BASE_URL", _UNIT_TEST_BASE_URL)

    # Keep the singleton and the global API proxy aligned with the patched URL.
    wandb_setup.singleton().settings.base_url = _UNIT_TEST_BASE_URL
    wandb.ensure_configured()


@pytest.fixture
def api() -> wandb.Api:
    """A fake wandb.Api instance.

    Unit tests can't talk to a local-testcontainer, so most methods on this
    will fail unless patched.
    """
    with unittest.mock.patch("wandb.sdk.wandb_login._verify_login"):
        return wandb.Api()


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
