import datetime
from typing import Any, Callable, Dict, List, Optional

import wandb
from wandb.integration.openai.autologging_utils import disable_autologging
from wandb.integration.openai.utils import (
    _gen_classes_to_patch,
    _patch_method_if_available,
    safe_patch,
)
from wandb.sdk.data_types import trace_tree


def results_to_trace_tree(
    request: Dict[str, Any], response: Dict[str, Any], results: List[trace_tree.Result]
) -> trace_tree.WBTraceTree:
    """Converts the request, response, and results into a trace tree.
    params:
        request: The request object
        response: The response object
        results: A list of results object
    returns:
        A trace tree object
    """
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


def parse_completion_request_and_response(
    request: Dict[str, Any], response: Dict[str, Any]
) -> trace_tree.WBTraceTree:
    """Parses and converts the request and response for the completion API to a trace tree.
    params:
        request: The request object
        response: The response object
    returns:
        A trace tree object
    """

    def format_request(request: Dict[str, Any]) -> str:
        """Formats the request object to a string.
        params:
            request: The request object
        returns:
            A string representation of the request object to be logged in a trace tree Result object.
        """
        prompt = f"\n\n**Prompt**: {request['prompt']}\n"
        return prompt

    def format_response_choice(choice: Dict[str, Any]) -> str:
        """Formats the choice in a response object to a string.
        params:
            choice: The choice object
        returns:
            A string representation of the choice object to be logged in a trace tree Result object.
        """
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


def parse_chat_completion_request_and_response(
    request: Dict[str, Any], response: Dict[str, Any]
) -> trace_tree.WBTraceTree:
    """Parses and converts the request and response for the chat completion API to a trace tree.
    params:
        request: The request object
        response: The response object
    returns:
        A trace tree object
    """

    def format_request(request: Dict[str, Any]) -> str:
        """Formats the request object to a string.
        params:
            request: The request object
        returns:
            A string representation of the request object to be logged in a trace tree Result object.
        """
        prompt = ""
        for message in request["messages"]:
            prompt += f"\n\n**{message['role']}**: {message['content']}\n"
        return prompt

    def format_response_choice(choice: Dict[str, Any]) -> str:
        """Formats the choice in a response object to a string.
        params:
            choice: The choice object
        returns:
            A string representation of the choice object to be logged in a trace tree Result object.
        """
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


def parse_edit_request_and_response(
    request: Dict[str, Any], response: Dict[str, Any]
) -> trace_tree.WBTraceTree:
    def format_request(request: Dict[str, Any]) -> str:
        """Formats the request object to a string.
        params:
            request: The request object
        returns:
            A string representation of the request object to be logged in a trace tree Result object.
        """
        prompt = f"\n\n**Instruction**: {request['instruction']}\n\n**Input**: {request['input']}\n"
        return prompt

    def format_response_choice(choice: Dict[str, Any]) -> str:
        """Formats the choice in a response object to a string.
        params:
            choice: The choice object
        returns:
            A string representation of the choice object to be logged in a trace tree Result object.
        """
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


def parse_request_and_response_by_object(
    request: Dict[str, Any], response: Dict[str, Any]
) -> Optional[trace_tree.WBTraceTree]:
    """Parses the request and response by object type.
    params:
        request: The request object
        response: The response object
    returns:
        A trace tree object or None if the object type is not supported.
    """
    if response["object"] == "text_completion":
        return parse_completion_request_and_response(request, response)
    elif response["object"] == "chat.completion":
        return parse_chat_completion_request_and_response(request, response)
    elif response["object"] == "edit":
        return parse_edit_request_and_response(request, response)
    else:
        return None


def initialize_run(**run_args) -> None:
    """Initializes a Weights & Biases run.
    params:
        run_args: The arguments to pass to wandb.init()
    returns:
        None
    """
    if wandb.run is None:
        wandb.init(**run_args)


def log_api_request_and_response(
    request: Dict[str, Any], response: Dict[str, Any]
) -> None:
    """Logs the API request and response to Weights & Biases.
    params:
        request: The request object
        response: The response object
    returns:
        None
    """

    # Log the API request and response to Weights & Biases
    trace = parse_request_and_response_by_object(request, response)
    if trace is not None:
        wandb.log({"trace": trace})


def create_impl_wandb(original: Callable, *args, **kwargs) -> Dict[str, Any]:
    """Patch function for Openai API methods that log results to Weights & Biases.
    params:
        original: The original API method to be patched
        args: The arguments to pass to the original API method
        kwargs: The keyword arguments to pass to the original API method
    returns:
        The response from the original API method
    """

    # Call the original API method
    response = original(*args, **kwargs)
    # Log the API request and response to Weights & Biases
    log_api_request_and_response(request=kwargs, response=response)
    return response


def autolog(**run_args) -> None:
    """Enables and configures autologging for the OpenAI API.
    params:
        run_args: The arguments to pass to wandb.init()
    returns:
        None
    """
    initialize_run(**run_args)
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


def disable_autolog() -> None:
    """Disables autologging for the OpenAI API and calls wandb.finish() if necessary.
    returns:
        None
    """

    def patched_fn_with_autolog_disabled(
        original: Callable, *args, **kwargs
    ) -> Dict[str, Any]:
        with disable_autologging():
            return original(*args, **kwargs)

    classes_to_patch = _gen_classes_to_patch()
    for class_def in classes_to_patch:
        for method_name in [
            "create",
        ]:
            safe_patch(
                "openai",
                class_def,
                method_name,
                patched_fn_with_autolog_disabled,
            )
    if wandb.run is not None:
        wandb.run.finish()
