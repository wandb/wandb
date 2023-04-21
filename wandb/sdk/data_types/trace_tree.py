"""This module contains the `WBTraceTree` media type, and the supporting dataclasses.

A `WBTraceTree` is a media object containing a root span and an
arbitrary model dump as a serializable dictionary. Logging such media type will
result in a W&B Trace Debugger panel being created in the workspace UI.
"""

import dataclasses
import hashlib
import json
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from wandb.data_types import _json_helper
from wandb.sdk.data_types import _dtypes
from wandb.sdk.data_types.base_types.media import Media

if TYPE_CHECKING:  # pragma: no cover
    from ..wandb_artifacts import Artifact as LocalArtifact
    from ..wandb_run import Run as LocalRun


class StatusCode(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"

    def __str__(self) -> str:
        return str(self.value)


class SpanKind(str, Enum):
    LLM = "LLM"
    CHAIN = "CHAIN"
    AGENT = "AGENT"
    TOOL = "TOOL"

    def __str__(self) -> str:
        return str(self.value)


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

    def add_attribute(self, key: str, value: Any) -> None:
        if self.attributes is None:
            self.attributes = {}
        self.attributes[key] = value

    def add_named_result(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        if self.results is None:
            self.results = []
        self.results.append(Result(inputs, outputs))

    def add_child_span(self, span: "Span") -> None:
        if self.child_spans is None:
            self.child_spans = []
        self.child_spans.append(span)


class WBTraceTree(Media):
    """Media object for trace tree data.

    Arguments:
        root_span (Span): The root span of the trace tree.
        model_dict (dict, optional): A dictionary containing the model dump.
            NOTE: model_dict is a completely-user-defined dict. The UI will render
            a JSON viewer for this dict, giving special treatment to dictionaries
            with a `_kind` key. This is because model vendors have such different
            serialization formats that we need to be flexible here.
    """

    _log_type = "wb_trace_tree"

    def __init__(
        self,
        root_span: Span,
        model_dict: typing.Optional[dict] = None,
    ):
        super().__init__()
        self._root_span = root_span
        self._model_dict = model_dict

    @classmethod
    def get_media_subdir(cls) -> str:
        return "media/wb_trace_tree"

    def to_json(self, run: Optional[Union["LocalRun", "LocalArtifact"]]) -> dict:
        res = {}
        res["_type"] = self._log_type
        # Here we use `dumps` to put things into string format. This is because
        # the complex data structures create problems for gorilla history to parquet.
        if self._model_dict is not None:
            model_dump_str = _safe_serialize(self._model_dict)
            res["model_hash"] = _hash_id(model_dump_str)
            res["model_dict_dumps"] = model_dump_str
        res["root_span_dumps"] = _safe_serialize(dataclasses.asdict(self._root_span))
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


def _fallback_serialize(obj: Any) -> str:
    try:
        return f"<<non-serializable: {type(obj).__qualname__}>>"
    except Exception:
        return "<<non-serializable>>"


def _safe_serialize(obj: dict) -> str:
    try:
        return json.dumps(
            _json_helper(obj, None),
            skipkeys=True,
            default=_fallback_serialize,
        )
    except Exception:
        return "{}"
