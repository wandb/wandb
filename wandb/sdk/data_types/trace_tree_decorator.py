# Experimental:
import time
import contextvars
from contextlib import contextmanager
import wandb
from typing import Any, Dict, List, Optional

from .trace_tree import Span, StatusCode, Result, WBTraceTree


def _current_time_ms() -> int:
    return int(time.time() * 1000)


class _LiveSpan(Span):
    """A span that can be used to track a live span.

    This class is experimental and subject to change.
    """

    _live_state: str = "UNSTARTED"

    def start(self):
        if self._live_state != "UNSTARTED":
            raise ValueError("Span must be unstarted before starting.")
        self._live_state = "STARTED"
        self.start_time_ms = _current_time_ms()

    def end(
        self, status_code: StatusCode = StatusCode.SUCCESS, status_message: str = ""
    ):
        if self._live_state != "STARTED":
            raise ValueError("Span must be started before ending.")
        self.live_state = "ENDED"
        self.end_time_ms = _current_time_ms()
        self.status_code = status_code
        self.status_message = status_message

    def add_attribute(self, key: str, value: Any):
        if self.attributes is None:
            self.attributes = {}
        self.attributes[key] = value

    def add_named_result(self, inputs: Dict[str, Any], outputs: Dict[str, Any]):
        if self.results is None:
            self.results = []
        self.results.append(Result(inputs, outputs))

    def add_result(
        self,
        input_args: List[Any] = [],
        input_kwargs: Dict[str, Any] = {},
        output: Any = None,
    ):
        if not isinstance(output, dict):
            output = {"output": output}
        inputs = {**{f"{i}": v for i, v in enumerate(input_args)}, **input_kwargs}
        self.add_named_result(inputs, output)

    def add_child_span(self, span: "Span"):
        if self.child_spans is None:
            self.child_spans = []
        self.child_spans.append(span)

    def make_child_span(self, name: str) -> "_LiveSpan":
        child_span = _LiveSpan(
            name=name,
        )
        self.add_child_span(child_span)
        return child_span


_CURRENT_SPAN: contextvars.ContextVar[Optional[_LiveSpan]] = contextvars.ContextVar(
    "_current_span", default=None
)


@contextmanager
def _new_span(name, run=None, key="trace_tree"):
    current_span = _CURRENT_SPAN.get()
    needs_flush_on_exit = current_span is None and run is not None
    if current_span is None:
        current_span = _LiveSpan(name=name)
    else:
        current_span = current_span.make_child_span(name)
    current_span.start()
    token = _CURRENT_SPAN.set(current_span)
    exception = None
    try:
        yield current_span
    except Exception as e:
        exception = e
        raise e
    finally:
        if exception is not None:
            current_span.end(StatusCode.ERROR, str(exception))
        current_span.end()
        _CURRENT_SPAN.reset(token)
        if needs_flush_on_exit:
            run.log({"trace_tree": WBTraceTree(current_span)})


class Tracer:
    _run = None

    def __init__(self, run_args):
        if wandb.run is not None:
            print("Using existing wandb run")
            self._run = wandb.run
        self._run = wandb.init(**run_args)

    def trace(self, name=None):
        def decorator(fn):
            nonlocal name
            if name is None:
                name = fn.__name__

            def wrapper(*args, **kwargs):
                with _new_span(name, self._run) as span:
                    res = fn(*args, **kwargs)
                    span.add_result(input_args=args, input_kwargs=kwargs, output=res)
                    return res

            return wrapper

        return decorator
