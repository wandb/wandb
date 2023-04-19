"""Common utilities for the LangChain integration.

This file exposes 4 primary functions:
- `print_wandb_init_message`: Prints a message to the user when the `WandbTracer` is initialized.
- `safely_convert_lc_run_to_wb_span`: Converts a LangChain Run into a W&B Trace Span.
- `safely_get_span_producing_model`: Retrieves the model that produced a given LangChain Run.
- `safely_convert_model_to_dict`: Converts a LangChain model into a dictionary.

These functions are used by the `WandbTracer` to extract and save the relevant information.
"""

from typing import TYPE_CHECKING, Any, Optional, Union

from langchain.agents import BaseSingleActionAgent
from langchain.callbacks.tracers.schemas import ChainRun, LLMRun, ToolRun

import wandb
from wandb.sdk.data_types import trace_tree

if TYPE_CHECKING:
    from langchain.callbacks.tracers.schemas import BaseRun
    from langchain.chains.base import Chain
    from langchain.llms.base import BaseLLM
    from langchain.schema import BaseLanguageModel
    from langchain.tools.base import BaseTool


PRINT_WARNINGS = True


def print_wandb_init_message(run_url: str) -> None:
    wandb.termlog(
        f"Streaming LangChain activity to W&B at {run_url}\n"
        "`WandbTracer` is currently in beta.\n"
        "Please report any issues to https://github.com/wandb/wandb/issues with the tag `langchain`."
    )


def safely_convert_lc_run_to_wb_span(run: "BaseRun") -> Optional["trace_tree.Span"]:
    try:
        return _convert_lc_run_to_wb_span(run)
    except Exception as e:
        if PRINT_WARNINGS:
            wandb.termwarn(
                f"Skipping trace saving - unable to safely convert LangChain Run into W&B Trace due to: {e}"
            )
    return None


def safely_get_span_producing_model(run: "BaseRun") -> Any:
    try:
        return run.serialized.get("_self")
    except Exception as e:
        if PRINT_WARNINGS:
            wandb.termwarn(
                f"Skipping model saving - unable to safely retrieve LangChain model due to: {e}"
            )
    return None


def safely_convert_model_to_dict(
    model: Union["BaseLanguageModel", "BaseLLM", "BaseTool", "Chain"]
) -> Optional[dict]:
    """Returns the model dict if possible, otherwise returns None.

    Given that Models are all user defined, this operation is not always possible.
    """
    data = None
    message = None
    try:
        data = model.dict()
    except Exception as e:
        message = str(e)
        if hasattr(model, "agent"):
            try:
                data = model.agent.dict()
            except Exception as e:
                message = str(e)

    if data is not None and not isinstance(data, dict):
        message = (
            f"Model's dict transformation resulted in {type(data)}, expected a dict."
        )
        data = None

    if data is not None:
        data = _replace_type_with_kind(data)
    else:
        if PRINT_WARNINGS:
            wandb.termwarn(
                f"Skipping model saving - unable to safely convert LangChain Model to dictionary due to: {message}"
            )

    return data


def _convert_lc_run_to_wb_span(run: "BaseRun") -> "trace_tree.Span":
    if isinstance(run, LLMRun):
        return _convert_llm_run_to_wb_span(run)
    elif isinstance(run, ChainRun):
        return _convert_chain_run_to_wb_span(run)
    elif isinstance(run, ToolRun):
        return _convert_tool_run_to_wb_span(run)
    else:
        return _convert_run_to_wb_span(run)


def _convert_llm_run_to_wb_span(run: "LLMRun") -> "trace_tree.Span":
    base_span = _convert_run_to_wb_span(run)

    if run.response is not None:
        base_span.attributes["llm_output"] = run.response.llm_output
    base_span.results = [
        trace_tree.Result(
            inputs={"prompt": prompt},
            outputs={
                f"gen_{g_i}": gen.text
                for g_i, gen in enumerate(run.response.generations[ndx])
            }
            if (
                run.response is not None
                and len(run.response.generations) > ndx
                and len(run.response.generations[ndx]) > 0
            )
            else None,
        )
        for ndx, prompt in enumerate(run.prompts or [])
    ]
    base_span.span_kind = trace_tree.SpanKind.LLM

    return base_span


def _convert_chain_run_to_wb_span(run: "ChainRun") -> "trace_tree.Span":
    base_span = _convert_run_to_wb_span(run)

    base_span.results = [trace_tree.Result(inputs=run.inputs, outputs=run.outputs)]
    base_span.child_spans = [
        _convert_lc_run_to_wb_span(child_run) for child_run in run.child_runs
    ]
    base_span.span_kind = (
        trace_tree.SpanKind.AGENT
        if isinstance(safely_get_span_producing_model(run), BaseSingleActionAgent)
        else trace_tree.SpanKind.CHAIN
    )

    return base_span


def _convert_tool_run_to_wb_span(run: "ToolRun") -> "trace_tree.Span":
    base_span = _convert_run_to_wb_span(run)

    base_span.attributes["action"] = run.action
    base_span.results = [
        trace_tree.Result(
            inputs={"input": run.tool_input}, outputs={"output": run.output}
        )
    ]
    base_span.child_spans = [
        _convert_lc_run_to_wb_span(child_run) for child_run in run.child_runs
    ]
    base_span.span_kind = trace_tree.SpanKind.TOOL

    return base_span


def _convert_run_to_wb_span(run: "BaseRun") -> "trace_tree.Span":
    attributes = {**run.extra} if run.extra else {}
    attributes["execution_order"] = run.execution_order

    return trace_tree.Span(
        span_id=str(run.id) if run.id is not None else None,
        name=run.serialized.get("name"),
        start_time_ms=run.start_time,
        end_time_ms=run.end_time,
        status_code=trace_tree.StatusCode.SUCCESS
        if run.error is None
        else trace_tree.StatusCode.ERROR,
        status_message=run.error,
        attributes=attributes,
    )


def _replace_type_with_kind(data: dict) -> dict:
    if isinstance(data, dict):
        # W&B TraceTree expects "_kind" instead of "_type" since `_type` is special
        # in W&B.
        if "_type" in data:
            _type = data.pop("_type")
            data["_kind"] = _type
        return {k: _replace_type_with_kind(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_replace_type_with_kind(v) for v in data]
    elif isinstance(data, tuple):
        return tuple(_replace_type_with_kind(v) for v in data)
    elif isinstance(data, set):
        return {_replace_type_with_kind(v) for v in data}
    else:
        return data
