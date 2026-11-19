import pathlib
import re
import subprocess

import pytest
import wandb
from google.protobuf import text_format
from wandb.proto import wandb_internal_pb2 as pb
from wandb.util import get_core_path

_WANDB_HEADER_PREFIX = b":W&B\xe1\xbe"
_RECORD_BLOCK = re.compile(
    r"# record \d+: \w+\n(.*?)(?=\n# record |\Z)",
    flags=re.DOTALL,
)


def _transaction_log_version(path: str) -> int:
    with open(path, "rb") as f:
        header = f.read(7)
    assert header[:6] == _WANDB_HEADER_PREFIX
    return header[6]


def _inspect_records(sync_file: str) -> list[pb.Record]:
    """Run `leet inspect` and parse each prototext stanza into a Record."""
    sync_path = pathlib.Path(sync_file)
    result = subprocess.run(
        [
            get_core_path(),
            "leet",
            "inspect",
            "--no-observability",
            "--run-file",
            str(sync_path),
            str(sync_path.parent.parent),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return [
        text_format.Parse(block, pb.Record())
        for block in _RECORD_BLOCK.findall(result.stdout)
    ]


@pytest.mark.parametrize(
    ("encoding", "version", "want_value_json", "want_kind"),
    [
        ("json", 0, "0.5", None),
        ("typed", 1, "", "number"),
        ("json,typed", 0, "0.5", "number"),
    ],
)
def test_transaction_log_history_encoding(
    encoding: str,
    version: int,
    want_value_json: str,
    want_kind: str | None,
):
    with wandb.init(
        mode="offline",
        settings=wandb.Settings(x_history_value_encoding=encoding),
    ) as run:
        run.log({"metric": 0.5}, step=0)

    sync_file = run.settings.sync_file
    assert _transaction_log_version(sync_file) == version

    history_items = []
    for record in _inspect_records(sync_file):
        if not record.HasField("history"):
            continue
        for item in record.history.item:
            if item.key == "metric" or list(item.nested_key) == ["metric"]:
                history_items.append(item)
    assert history_items
    for item in history_items:
        assert item.value_json == want_value_json
        assert item.WhichOneof("value") == want_kind
        if want_kind == "number":
            assert item.number == 0.5
