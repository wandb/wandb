#

import re

import wandb
from wandb.proto.wandb_telemetry_pb2 import Imports as TelemetryImports
from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import ContextManager, Dict, List, Type, Optional
    from types import TracebackType

    # avoid cycle, use string type reference
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from .. import wandb_run


_LABEL_TOKEN: str = "@wandbcode{"


class _TelemetryObject(object):
    _run: Optional["wandb_run.Run"]

    def __init__(self, run: "wandb_run.Run" = None) -> None:
        self._run = run or wandb.run
        self._obj = TelemetryRecord()

    def __enter__(self) -> TelemetryRecord:
        return self._obj

    def __exit__(
        self,
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ) -> None:
        if not self._run:
            return
        self._run._telemetry_callback(self._obj)


def context(run: "wandb_run.Run" = None) -> ContextManager[TelemetryRecord]:
    return _TelemetryObject(run=run)


MATCH_RE = re.compile(r"(?P<code>[a-zA-Z0-9_-]+)[,}](?P<rest>.*)")


def _parse_label_lines(lines: List[str]) -> Dict[str, str]:
    seen = False
    ret = {}
    for line in lines:
        idx = line.find(_LABEL_TOKEN)
        if idx < 0:
            # Stop parsing on first non token line after match
            if seen:
                break
            continue
        seen = True
        label_str = line[idx + len(_LABEL_TOKEN) :]

        # match identifier (first token without key=value syntax (optional)
        # Note: Parse is fairly permissive as it doesnt enforce strict syntax
        r = MATCH_RE.match(label_str)
        if r:
            ret["code"] = r.group("code").replace("-", "_")
            label_str = r.group("rest")

        # match rest of tokens on one line
        tokens = re.findall(
            r'([a-zA-Z0-9_]+)\s*=\s*("[a-zA-Z0-9_-]*"|[a-zA-Z0-9_-]*)[,}]', label_str
        )
        for k, v in tokens:
            ret[k] = v.strip('"').replace("-", "_")
    return ret


__all__ = [
    "TelemetryImports",
    "TelemetryRecord",
    "context",
]
