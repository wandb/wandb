"""Parser for local .wandb run transaction log files.

Reads a .wandb binary file and yields records as JSON-serializable dicts.
The output is suitable for writing as JSONL (newline-delimited JSON).

Example usage::

    from wandb.sdk.lib.run_file_parser import RunFileParser

    parser = RunFileParser("run-abc123.wandb")
    for line in parser.to_jsonl():
        print(line)
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore
from wandb.sdk.lib.proto_util import message_to_dict


class RunFileParser:
    """Parse a .wandb transaction log file into JSON-serializable records.

    Args:
        path: Path to the .wandb file to parse.
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def raw_records(
        self,
    ) -> Iterator[tuple[str, wandb_internal_pb2.Record]]:
        """Iterate over raw protobuf records from the transaction log.

        Yields:
            ``(record_type, pb)`` tuples where *record_type* is the oneof field
            name and *pb* is the parsed :class:`Record` protobuf message.

        Raises:
            ValueError: If the file is empty or invalid.
        """
        ds = datastore.DataStore()
        try:
            ds.open_for_scan(self._path)
        except AssertionError as e:
            raise ValueError(f".wandb file is empty or invalid: {e}") from e

        while True:
            try:
                data = ds.scan_data()
            except AssertionError as e:
                if ds.in_last_block():
                    wandb.termwarn(
                        f".wandb file is incomplete ({e}), be sure to sync this run "
                        "again once it's finished"
                    )
                    break
                raise
            if data is None:
                break

            pb = wandb_internal_pb2.Record()
            pb.ParseFromString(data)
            record_type = pb.WhichOneof("record_type")
            if record_type is None:
                continue

            yield record_type, pb

    def to_json(
        self,
        record_types: list[str] | None = None,
    ) -> Iterator[str]:
        """Iterate over records as JSONL strings.

        Args:
            expand_values: When True, expand ``value_json`` string fields into
                native JSON values for records that carry key/value item lists
                (history, summary, config, stats).
            record_types: Optional list of record types to include. If None,
                all records are returned.

        Yields:
            One JSON string per record (no trailing newline).
        """
        for record_type, pb in self.raw_records():
            if record_types and record_type not in record_types:
                continue
            full_dict = message_to_dict(pb)
            record: dict = {"record_type": record_type}
            if pb.num:
                record["num"] = pb.num
            record.update(full_dict.get(record_type, {}))

            yield json.dumps(record, default=str)
