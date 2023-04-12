import dataclasses
import hashlib
import json
import typing

from wandb.data_types import _json_helper
from wandb.sdk.data_types import _dtypes
from wandb.sdk.data_types.base_types.media import Media

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class StatusCode(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class SpanKind(str, Enum):
    LLM = "LLM"
    CHAIN = "CHAIN"
    AGENT = "AGENT"
    TOOL = "TOOL"


@dataclass()
class Result:
    inputs: Optional[Dict[str, Any]] = field(default=None)
    outputs: Optional[Dict[str, Any]] = field(default=None)


@dataclass()
class Span:
    span_id: Optional[str] = field(default=None)
    name: Optional[str] = field(default=None)
    start_time_ms: Optional[int] = field(default=None)
    end_time_ms: Optional[int] = field(default=None)
    status_code: Optional[StatusCode] = field(default=None)
    status_message: Optional[str] = field(default=None)
    attributes: Optional[Dict[str, Any]] = field(default=None)
    results: Optional[List[Result]] = field(default=None)
    child_spans: Optional[List["Span"]] = field(default=None)
    span_kind: Optional[SpanKind] = field(default=None)


class WBTraceTree(Media):
    """Media object for trace tree data.
    Arguments:
        root_span (Span): The root span of the trace tree.
        model_dump (dict, optional): A dictionary containing the model dump.
        NOTE: model_dump is a completely-user-defined dict. The UI will render
        a JSON viewer for this dict, giving special treatment to dictionaries
        with a _kind key. This is because model vendors have such different
        serialization formats that we need to be flexible here.
    """

    _log_type = "wb_trace_tree"

    def __init__(
        self,
        root_span: Span,
        model_dump: typing.Optional[dict] = None,
    ):
        super().__init__()
        self._root_span = root_span
        self._model_dump = model_dump

    @classmethod
    def get_media_subdir(cls) -> str:
        return "media/wb_trace_tree"

    def to_json(self, run) -> dict:
        res = {}
        res["_type"] = self._log_type
        if self._model_dump is None:
            res["model_hash"] = None
            res["model_dump"] = None
        else:
            model_dump_str = _safe_serialize(self._model_dump)
            res["model_hash"] = _hash_id(model_dump_str)
            res["model_dump"] = json.loads(model_dump_str)
        res["root_span"] = _json_helper(dataclasses.asdict(self._root_span), None)
        return res

    def is_bound(self) -> bool:
        return True


class _WBTraceTreeFileType(_dtypes.Type):
    name = "wb_trace_tree"
    types = [WBTraceTree]


_dtypes.TypeRegistry.add(_WBTraceTreeFileType)


# generate a deterministic 16 character id based on input string
def _hash_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def _safe_serialize(obj):
    return json.dumps(
        _json_helper(obj, None),
        skipkeys=True,
        default=lambda o: f"<<non-serializable: {type(o).__qualname__}>>",
    )
