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

import wandb
import wandb.data_types
from wandb.sdk.data_types import _dtypes
from wandb.sdk.data_types.base_types.media import Media

if TYPE_CHECKING:  # pragma: no cover
    from wandb.sdk.artifacts.artifact import Artifact

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

    def to_json(self, run: Optional[Union["LocalRun", "Artifact"]]) -> dict:
        res = {"_type": self._log_type}
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
            wandb.data_types._json_helper(obj, None),
            skipkeys=True,
            default=_fallback_serialize,
        )
    except Exception:
        return "{}"


class TraceAttribute:
    """Descriptor for accessing and setting attributes of the `Trace` class."""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: "Trace", owner: type) -> Any:
        return getattr(instance._span, self.name)

    def __set__(self, instance: "Trace", value: Any) -> None:
        setattr(instance._span, self.name, value)


class Trace:
    """A simplification of WBTraceTree and Span to manage a trace - a collection of spans, their metadata and hierarchy.

    Args:
        name: (str) The name of the root span.
        kind: (str, optional) The kind of the root span.
        status_code: (str, optional) The status of the root span, either "error" or "success".
        status_message: (str, optional) Any status message associated with the root span.
        metadata: (dict, optional) Any additional metadata for the root span.
        start_time_ms: (int, optional) The start time of the root span in milliseconds.
        end_time_ms: (int, optional) The end time of the root span in milliseconds.
        inputs: (dict, optional) The named inputs of the root span.
        outputs: (dict, optional) The named outputs of the root span.
        model_dict: (dict, optional) A json serializable dictionary containing the model architecture details.

    Example:
        .. code-block:: python
        ```
        trace = Trace(
            name="My awesome Model",
            kind="LLM",
            status_code= "SUCCESS",
            metadata={"attr_1": 1, "attr_2": 2,},
            start_time_ms=int(round(time.time() * 1000)),
            end_time_ms=int(round(time.time() * 1000))+1000,
            inputs={"user": "How old is google?"},
            outputs={"assistant": "25 years old"},
            model_dict={"_kind": "openai", "api_type": "azure"}
              )
        run = wandb.init(project=<my_awesome_project>,)
        trace.log("my_trace")
        wandb.finish()
        ```
    """

    name = TraceAttribute()
    status_code = TraceAttribute()
    status_message = TraceAttribute()
    start_time_ms = TraceAttribute()
    end_time_ms = TraceAttribute()

    def __init__(
        self,
        name: str,
        kind: Optional[str] = None,
        status_code: Optional[str] = None,
        status_message: Optional[str] = None,
        metadata: Optional[dict] = None,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        inputs: Optional[dict] = None,
        outputs: Optional[dict] = None,
        model_dict: Optional[dict] = None,
    ):
        self._span = self._assert_and_create_span(
            name=name,
            kind=kind,
            status_code=status_code,
            status_message=status_message,
            metadata=metadata,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            inputs=inputs,
            outputs=outputs,
        )
        if model_dict is not None:
            assert isinstance(model_dict, dict), "Model dict must be a dictionary"
        self._model_dict = model_dict

    def _assert_and_create_span(
        self,
        name: str,
        kind: Optional[str] = None,
        status_code: Optional[str] = None,
        status_message: Optional[str] = None,
        metadata: Optional[dict] = None,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        inputs: Optional[dict] = None,
        outputs: Optional[dict] = None,
    ) -> Span:
        """Utility to assert the validity of the span parameters and create a span object.

        Args:
            name: The name of the span.
            kind: The kind of the span.
            status_code: The status code of the span.
            status_message: The status message of the span.
            metadata: Dictionary of metadata to be logged with the span.
            start_time_ms: Start time of the span in milliseconds.
            end_time_ms: End time of the span in milliseconds.
            inputs: Dictionary of inputs to be logged with the span.
            outputs: Dictionary of outputs to be logged with the span.

        Returns:
            A Span object.
        """
        if kind is not None:
            assert (
                kind.upper() in SpanKind.__members__
            ), "Invalid span kind, can be one of 'LLM', 'AGENT', 'CHAIN', 'TOOL'"
            kind = SpanKind(kind.upper())
        if status_code is not None:
            assert (
                status_code.upper() in StatusCode.__members__
            ), "Invalid status code, can be one of 'SUCCESS' or 'ERROR'"
            status_code = StatusCode(status_code.upper())
        if inputs is not None:
            assert isinstance(inputs, dict), "Inputs must be a dictionary"
        if outputs is not None:
            assert isinstance(outputs, dict), "Outputs must be a dictionary"
        if inputs or outputs:
            result = Result(inputs=inputs, outputs=outputs)
        else:
            result = None

        if metadata is not None:
            assert isinstance(metadata, dict), "Metadata must be a dictionary"

        return Span(
            name=name,
            span_kind=kind,
            status_code=status_code,
            status_message=status_message,
            attributes=metadata,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            results=[result] if result else None,
        )

    def add_child(
        self,
        child: "Trace",
    ) -> "Trace":
        """Utility to add a child span to the current span of the trace.

        Args:
            child: The child span to be added to the current span of the trace.

        Returns:
            The current trace object with the child span added to it.
        """
        self._span.add_child_span(child._span)
        if self._model_dict is not None and child._model_dict is not None:
            self._model_dict.update({child._span.name: child._model_dict})
        return self

    def add_inputs_and_outputs(self, inputs: dict, outputs: dict) -> "Trace":
        """Add a result to the span of the current trace.

        Args:
            inputs: Dictionary of inputs to be logged with the span.
            outputs: Dictionary of outputs to be logged with the span.

        Returns:
            The current trace object with the result added to it.
        """
        if self._span.results is None:
            result = Result(inputs=inputs, outputs=outputs)
            self._span.results = [result]
        else:
            result = Result(inputs=inputs, outputs=outputs)
            self._span.results.append(result)
        return self

    def add_metadata(self, metadata: dict) -> "Trace":
        """Add metadata to the span of the current trace."""
        if self._span.attributes is None:
            self._span.attributes = metadata
        else:
            self._span.attributes.update(metadata)
        return self

    @property
    def metadata(self) -> Optional[Dict[str, str]]:
        """Get the metadata of the trace.

        Returns:
            Dictionary of metadata.
        """
        return self._span.attributes

    @metadata.setter
    def metadata(self, value: Dict[str, str]) -> None:
        """Set the metadata of the trace.

        Args:
            value: Dictionary of metadata to be set.
        """
        if self._span.attributes is None:
            self._span.attributes = value
        else:
            self._span.attributes.update(value)

    @property
    def inputs(self) -> Optional[Dict[str, str]]:
        """Get the inputs of the trace.

        Returns:
            Dictionary of inputs.
        """
        return self._span.results[-1].inputs if self._span.results else None

    @inputs.setter
    def inputs(self, value: Dict[str, str]) -> None:
        """Set the inputs of the trace.

        Args:
            value: Dictionary of inputs to be set.
        """
        if self._span.results is None:
            result = Result(inputs=value, outputs={})
            self._span.results = [result]
        else:
            result = Result(inputs=value, outputs=self._span.results[-1].outputs)
            self._span.results.append(result)

    @property
    def outputs(self) -> Optional[Dict[str, str]]:
        """Get the outputs of the trace.

        Returns:
            Dictionary of outputs.
        """
        return self._span.results[-1].outputs if self._span.results else None

    @outputs.setter
    def outputs(self, value: Dict[str, str]) -> None:
        """Set the outputs of the trace.

        Args:
            value: Dictionary of outputs to be set.
        """
        if self._span.results is None:
            result = Result(inputs={}, outputs=value)
            self._span.results = [result]
        else:
            result = Result(inputs=self._span.results[-1].inputs, outputs=value)
            self._span.results.append(result)

    @property
    def kind(self) -> Optional[str]:
        """Get the kind of the trace.

        Returns:
            The kind of the trace.
        """
        return self._span.span_kind.value if self._span.span_kind else None

    @kind.setter
    def kind(self, value: str) -> None:
        """Set the kind of the trace.

        Args:
            value: The kind of the trace to be set.
        """
        assert (
            value.upper() in SpanKind.__members__
        ), "Invalid span kind, can be one of 'LLM', 'AGENT', 'CHAIN', 'TOOL'"
        self._span.span_kind = SpanKind(value.upper())

    def log(self, name: str) -> None:
        """Log the trace to a wandb run.

        Args:
            name: The name of the trace to be logged
        """
        trace_tree = WBTraceTree(self._span, self._model_dict)
        assert (
            wandb.run is not None
        ), "You must call wandb.init() before logging a trace"
        assert len(name.strip()) > 0, "You must provide a valid name to log the trace"
        wandb.run.log({name: trace_tree})
