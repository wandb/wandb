import functools
import datetime

import wandb
from wandb.integration.openai import gorilla
from wandb.integration.openai.utils import (
    _gen_classes_to_patch,
    _patch_method_if_available,
)
from wandb.sdk.data_types import trace_tree


def results_to_trace_tree(request, response, results):
    span = trace_tree.Span(
        name=f"{response.get('model', 'openai')}_{response['object']}_{response.get('created')}",
        attributes=response,
        start_time_ms=int(round(response["created"] * 1000)),
        end_time_ms=int(round(datetime.datetime.now().timestamp() * 1000)),
        span_kind=trace_tree.SpanKind.LLM,
        results=results,
    )
    model_obj = {"request": request, "response": response, "_kind": "openai"}
    return trace_tree.WBTraceTree(root_span=span, model_dict=model_obj)


def parse_completion_request_and_response(request, response):
    def format_request(request):
        prompt = f"\n\n**Prompt**: {request['prompt']}\n"
        return prompt

    def format_response_choice(choice):
        choice = f"\n\n**Completion**: {choice['text']}\n"
        return choice

    results = [
        trace_tree.Result(
            inputs={"request": format_request(request)},
            outputs={"response": format_response_choice(choice)},
        )
        for choice in response["choices"]
    ]
    trace = results_to_trace_tree(request, response, results)
    return trace


def parse_chat_completion_request_and_response(request, response):
    def format_request(request):
        prompt = ""
        for message in request["messages"]:
            prompt += f"\n\n**{message['role']}**: {message['content']}\n"
        return prompt

    def format_response_choice(choice):
        return f"\n\n**{choice['message']['role']}**: {choice['message']['content']}\n"

    results = [
        trace_tree.Result(
            inputs={"request": format_request(request)},
            outputs={"response": format_response_choice(choice)},
        )
        for choice in response["choices"]
    ]
    trace = results_to_trace_tree(request, response, results)
    return trace


def parse_edit_request_and_response(request, response):
    def format_request(request):
        prompt = f"\n\n**Instruction**: {request['instruction']}\n\n**Input**: {request['input']}\n"
        return prompt

    def format_response_choice(choice):
        choice = f"\n\n**Edited**: {choice['text']}\n"
        return choice

    results = [
        trace_tree.Result(
            inputs={"request": format_request(request)},
            outputs={"response": format_response_choice(choice)},
        )
        for choice in response["choices"]
    ]
    trace = results_to_trace_tree(request, response, results)
    return trace


def parse_request_and_response_by_object(request, response):
    if response["object"] == "text_completion":
        return parse_completion_request_and_response(request, response)
    elif response["object"] == "chat.completion":
        return parse_chat_completion_request_and_response(request, response)
    elif response["object"] == "edit":
        return parse_edit_request_and_response(request, response)
    else:
        return None


def log_api_request_and_response(request, response):
    """Logs the API request and response to Weights & Biases."""
    _run = wandb.run if wandb.run is not None else wandb.init(project="openai_logging")
    # Log the API request and response to Weights & Biases
    trace = parse_request_and_response_by_object(request, response)
    if trace is not None:
        _run.log({"trace": trace})


def create_impl_wandb(original, *args, **kwargs):
    """Patches the OpenAI API to log results to Weights & Biases."""

    # Patch the API call to log results to Weights & Biases
    response = original(*args, **kwargs)
    log_api_request_and_response(request=kwargs, response=response)
    return response


def autolog():
    """Enables (or disables) and configures autologging for the OpenAI API."""
    classes_to_patch = _gen_classes_to_patch()

    for class_def in classes_to_patch:
        for method_name in [
            "create",
        ]:
            _patch_method_if_available(
                "openai",
                class_def,
                method_name,
                create_impl_wandb,
            )
