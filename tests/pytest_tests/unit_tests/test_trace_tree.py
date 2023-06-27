import pytest
from wandb.sdk.data_types.trace_tree import Span, SpanKind, StatusCode, Trace


def test_trace_creation():
    t = Trace(name="test_trace", kind="LLM", status_code="SUCCESS")
    assert isinstance(t._span, Span)
    assert t._span.name == "test_trace"
    assert t._span.span_kind == SpanKind.LLM
    assert t._span.status_code == StatusCode.SUCCESS


def test_invalid_span_kind():
    with pytest.raises(AssertionError):
        _ = Trace(name="test_trace", kind="INVALID_KIND", status_code="SUCCESS")


def test_invalid_status_code():
    with pytest.raises(AssertionError):
        _ = Trace(name="test_trace", kind="LLM", status_code="INVALID_STATUS_CODE")


def test_trace_add_child():
    parent_trace = Trace(name="parent_trace", kind="LLM", status_code="SUCCESS")
    child_trace = Trace(name="child_trace", kind="LLM", status_code="SUCCESS")

    parent_trace.add_child(child_trace)

    assert child_trace._span in parent_trace._span.child_spans


def test_trace_add_metadata():
    t = Trace(name="test_trace", kind="LLM", status_code="SUCCESS")

    t.add_metadata({"key": "value"})

    assert "key" in t._span.attributes
    assert t._span.attributes["key"] == "value"


def test_trace_add_inputs_and_outputs():
    t = Trace(name="test_trace", kind="LLM", status_code="SUCCESS")

    inputs = {"input_key": "input_value"}
    outputs = {"output_key": "output_value"}
    t.add_inputs_and_outputs(inputs, outputs)
    assert len(t._span.results) == 1
    assert t._span.results[0].inputs == inputs
    assert t._span.results[0].outputs == outputs

    t.add_inputs_and_outputs(inputs, outputs)
    assert len(t._span.results) == 2
    assert t._span.results[1].inputs == inputs
    assert t._span.results[1].outputs == outputs
