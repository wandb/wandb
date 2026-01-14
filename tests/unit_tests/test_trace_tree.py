import time

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


def test_trace_creation_with_optional_arguments():
    t = Trace(
        name="test_trace",
        kind="LLM",
        status_code="SUCCESS",
        status_message="Trace completed successfully",
        metadata={"key": "value"},
        start_time_ms=1000,
        end_time_ms=2000,
        inputs={"input_key": "input_value"},
        outputs={"output_key": "output_value"},
        model_dict={"_kind": "openai", "api_type": "azure"},
    )
    assert isinstance(t._span, Span)
    assert t._span.name == "test_trace"
    assert t._span.span_kind == SpanKind.LLM
    assert t._span.status_code == StatusCode.SUCCESS
    assert t._span.status_message == "Trace completed successfully"
    assert t._span.attributes == {"key": "value"}
    assert t._span.start_time_ms == 1000
    assert t._span.end_time_ms == 2000
    assert len(t._span.results) == 1
    assert t._span.results[0].inputs == {"input_key": "input_value"}
    assert t._span.results[0].outputs == {"output_key": "output_value"}
    assert t._model_dict == {"_kind": "openai", "api_type": "azure"}


def test_trace_add_child_with_model_dict():
    parent_trace = Trace(
        name="parent_trace",
        kind="LLM",
        status_code="SUCCESS",
        model_dict={"_kind": "openai"},
    )
    child_trace = Trace(
        name="child_trace",
        kind="LLM",
        status_code="SUCCESS",
        model_dict={"_kind": "azure"},
    )

    parent_trace.add_child(child_trace)

    assert child_trace._span in parent_trace._span.child_spans
    assert parent_trace._model_dict == {
        "_kind": "openai",
        "child_trace": {"_kind": "azure"},
    }


def test_trace_add_inputs_and_outputs_with_existing_results():
    t = Trace(name="test_trace", kind="LLM", status_code="SUCCESS")

    inputs1 = {"input_key1": "input_value1"}
    outputs1 = {"output_key1": "output_value1"}
    t.add_inputs_and_outputs(inputs1, outputs1)
    assert len(t._span.results) == 1
    assert t._span.results[0].inputs == inputs1
    assert t._span.results[0].outputs == outputs1

    inputs2 = {"input_key2": "input_value2"}
    outputs2 = {"output_key2": "output_value2"}
    t.add_inputs_and_outputs(inputs2, outputs2)
    assert len(t._span.results) == 2
    assert t._span.results[1].inputs == inputs2
    assert t._span.results[1].outputs == outputs2


def test_trace_log_without_wandb_run():
    t = Trace(name="test_trace", kind="LLM", status_code="SUCCESS")

    with pytest.raises(AssertionError):
        t.log("my_trace")


def test_trace_creation_with_all_params():
    start_time = int(time.time() * 1000)
    end_time = start_time + 1000

    inputs = {"input1": "foo"}
    outputs = {"output1": "bar"}

    t = Trace(
        name="test",
        kind="LLM",
        status_code="SUCCESS",
        status_message="All good",
        metadata={"k1": "v1"},
        start_time_ms=start_time,
        end_time_ms=end_time,
        inputs=inputs,
        outputs=outputs,
    )

    assert t.name == "test"
    assert t.status_code == "SUCCESS"
    assert t.status_message == "All good"
    assert t.metadata == {"k1": "v1"}
    assert t.start_time_ms == start_time
    assert t.end_time_ms == end_time
    assert t.inputs == inputs
    assert t.outputs == outputs


def test_invalid_metadata_type():
    with pytest.raises(AssertionError):
        Trace(name="test", metadata="invalid")


def test_invalid_inputs_outputs_type():
    with pytest.raises(AssertionError):
        Trace(name="test", inputs="invalid")

    with pytest.raises(AssertionError):
        Trace(name="test", outputs="invalid")


def test_trace_metadata_accessor():
    t = Trace(name="test")
    t.metadata = {"k1": "v1"}
    assert t.metadata == {"k1": "v1"}


def test_trace_inputs_accessor():
    inputs = {"input1": "foo"}
    t = Trace(name="test")
    t.inputs = inputs
    assert t.inputs == inputs


def test_trace_outputs_accessor():
    outputs = {"output1": "bar"}
    t = Trace(name="test")
    t.outputs = outputs
    assert t.outputs == outputs


def test_set_new_metadata():
    t = Trace("test")
    t.metadata = {"new": "metadata"}
    assert t.metadata == {"new": "metadata"}


def test_set_new_inputs():
    t = Trace("test")
    t.inputs = {"new": "inputs"}
    assert t.inputs == {"new": "inputs"}


def test_set_new_outputs():
    t = Trace("test")
    t.outputs = {"new": "outputs"}
    assert t.outputs == {"new": "outputs"}


def test_overwrite_metadata():
    t = Trace("test", metadata={"old": "metadata"})
    t.metadata = {"new": "metadata"}
    assert t.metadata == {"old": "metadata", "new": "metadata"}


def test_overwrite_inputs():
    t = Trace("test", inputs={"old": "inputs"})
    t.inputs = {"new": "inputs"}
    assert t.inputs == {"new": "inputs"}


def test_overwrite_outputs():
    t = Trace("test", outputs={"old": "outputs"})
    t.outputs = {"new": "outputs"}
    assert t.outputs == {"new": "outputs"}


def test_trace_log(mocker):
    t = Trace(name="test")
    mock_run = mocker.MagicMock()
    mocker.patch("wandb.run", mock_run)
    mock_log = mocker.patch.object(mock_run, "log")

    t.log("trace")

    mock_log.assert_called_once_with({"trace": mocker.ANY})


def test_invalid_model_dict_type():
    with pytest.raises(AssertionError):
        Trace("test", model_dict="invalid")


def test_trace_metadata_setter_with_existing_values():
    t = Trace(name="test")
    t.metadata = {"k1": "v1"}
    t.metadata = {"k2": "v2"}
    assert t.metadata == {"k1": "v1", "k2": "v2"}


def test_trace_inputs_outputs_setter_with_existing_values():
    inputs1 = {"input1": "foo"}
    outputs1 = {"output1": "bar"}
    inputs2 = {"input2": "baz"}
    outputs2 = {"output2": "qux"}

    t = Trace(name="test")
    t.inputs = inputs1
    t.outputs = outputs1
    t.inputs = inputs2
    t.outputs = outputs2

    assert t.inputs == inputs2
    assert t.outputs == outputs2


def test_trace_log_without_name(mocker):
    t = Trace(name="test")

    mock_run = mocker.MagicMock()
    mocker.patch("wandb.run", mock_run)
    mock_log = mocker.patch.object(mock_run, "log")

    with pytest.raises(AssertionError):
        t.log("")

    mock_log.assert_not_called()


def test_trace_model_dict(mocker):
    model_dict = {"_kind": "test_model"}
    t = Trace(name="test", model_dict=model_dict)

    mock_run = mocker.MagicMock()
    mocker.patch("wandb.run", mock_run)
    mock_log = mocker.patch.object(mock_run, "log")

    t.log("trace")

    called_model_dict = mock_log.call_args[0][0]["trace"]._model_dict
    assert called_model_dict == model_dict


def test_trace_child_model_dict(mocker):
    parent_model_dict = {"_kind": "parent"}
    child_model_dict = {"_kind": "child"}

    parent = Trace(name="parent", model_dict=parent_model_dict)
    child = Trace(name="child", model_dict=child_model_dict)

    parent.add_child(child)

    mock_run = mocker.MagicMock()
    mocker.patch("wandb.run", mock_run)
    mock_log = mocker.patch.object(mock_run, "log")

    parent.log("trace")

    called_model_dict = mock_log.call_args[0][0]["trace"]._model_dict
    assert called_model_dict == {**parent_model_dict, "child": child_model_dict}
