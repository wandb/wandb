from queue import Queue
from typing import Callable, Dict, Generator, List

import pytest

# --------------------------------
# Fixtures for user test point
# --------------------------------


class RecordsUtil:
    def __init__(self, queue: "Queue") -> None:
        self.records = []
        while not queue.empty():
            self.records.append(queue.get())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, name: str) -> Generator:
        for record in self.records:
            yield from self.resolve_item(record, name)

    @staticmethod
    def resolve_item(obj, attr: str, sep: str = ".") -> List:
        for name in attr.split(sep):
            if not obj.HasField(name):
                return []
            obj = getattr(obj, name)
        return [obj]

    @staticmethod
    def dictify(obj, key: str = "key", value: str = "value_json") -> Dict:
        return {getattr(item, key): getattr(item, value) for item in obj}

    @property
    def config(self) -> List:
        return [self.dictify(_c.update) for _c in self["config"]]

    @property
    def history(self) -> List:
        return [self.dictify(_h.item) for _h in self["history"]]

    @property
    def partial_history(self) -> List:
        return [self.dictify(_h.item) for _h in self["request.partial_history"]]

    @property
    def preempting(self) -> List:
        return list(self["preempting"])

    @property
    def summary(self) -> List:
        return list(self["summary"])

    @property
    def files(self) -> List:
        return list(self["files"])

    @property
    def metric(self):
        return list(self["metric"])


@pytest.fixture
def parse_records() -> Generator[Callable, None, None]:
    def records_parser_fn(q: "Queue") -> RecordsUtil:
        return RecordsUtil(q)

    yield records_parser_fn
