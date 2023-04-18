import logging
import sys
import time
from typing import Any, Dict, List, Optional, TypeVar

import wandb.sdk
import wandb.util
from wandb.sdk.data_types import trace_tree

if sys.version_info >= (3, 8):
    from typing import Literal, Protocol
else:
    from typing_extensions import Literal, Protocol


openai = wandb.util.get_module(
    name="openai",
    required="To use the W&B OpenAI Autolog, you need to have the `openai` python "
    "package installed. Please install it with `pip install openai`.",
    lazy=False,
)


logger = logging.getLogger(__name__)


K = TypeVar("K", bound=str)
V = TypeVar("V")


class OpenAIResponse(Protocol[K, V]):
    # contains a (known) object attribute
    object: Literal["chat.completion", "edit", "text_completion"]

    def __getitem__(self, key: K) -> V:
        ...  # pragma: no cover

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        ...  # pragma: no cover


class Timer:
    def __init__(self) -> None:
        self.start: float = time.perf_counter()
        self.stop: float = self.start

    def __enter__(self) -> "Timer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return self.stop - self.start


class OpenAIRequestResponseResolver:
    def __call__(
        self,
        request: Dict[str, Any],
        response: OpenAIResponse,
        time_elapsed: float,
    ) -> Optional[trace_tree.WBTraceTree]:
        try:
            if response["object"] == "edit":
                return self._resolve_edit(request, response, time_elapsed)
            # todo: the other dudes
        except Exception as e:
            logger.warning(f"Failed to resolve request/response: {e}")
        return None

    @staticmethod
    def results_to_trace_tree(
        request: Dict[str, Any],
        response: OpenAIResponse,
        results: List[trace_tree.Result],
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        """Converts the request, response, and results into a trace tree.

        params:
            request: The request object
            response: The response object
            results: A list of results object
        returns:
            A trace tree object.
        """
        start_time_ms = int(round(response["created"] * 1000))
        end_time_ms = start_time_ms + int(round(time_elapsed * 1000))
        span = trace_tree.Span(
            name=f"{response.get('model', 'openai')}_{response['object']}_{response.get('created')}",
            attributes=dict(response),  # type: ignore
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            span_kind=trace_tree.SpanKind.LLM,
            results=results,
        )
        model_obj = {"request": request, "response": response, "_kind": "openai"}
        return trace_tree.WBTraceTree(root_span=span, model_dict=model_obj)

    def _resolve_edit(
        self,
        request: Dict[str, Any],
        response: OpenAIResponse,
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        def format_request(_request: Dict[str, Any]) -> str:
            """Formats the request object to a string.

            params:
                _request: The request object
            returns:
                A string representation of the request object to be logged
                in a trace tree Result object.
            """
            prompt = (
                f"\n\n**Instruction**: {_request['instruction']}\n\n"
                f"**Input**: {_request['input']}\n"
            )
            return prompt

        def format_response_choice(_choice: Dict[str, Any]) -> str:
            """Formats the choice in a response object to a string.

            params:
                choice: The choice object
            returns:
                A string representation of the choice object to be logged
                in a trace tree Result object.
            """
            choice = f"\n\n**Edited**: {_choice['text']}\n"
            return choice

        results = [
            trace_tree.Result(
                inputs={"request": format_request(request)},
                outputs={"response": format_response_choice(choice)},
            )
            for choice in response["choices"]
        ]
        trace = self.results_to_trace_tree(request, response, results, time_elapsed)
        return trace


class PatchOpenAIAPI:
    symbols: List[Literal["Edit", "Completion", "ChatCompletion"]] = [
        "Edit",
        "Completion",
        "ChatCompletion",
    ]

    def __init__(self):
        self.original_methods: Dict[str, Any] = {}
        self.resolver = OpenAIRequestResponseResolver()

    def patch(self, run: "wandb.sdk.wandb_run.Run"):
        for symbol in self.symbols:
            original = getattr(openai, symbol).create

            def method_factory(original_method: Any):
                def create(*args, **kwargs):
                    with Timer() as timer:
                        result = original_method(*args, **kwargs)
                    trace = self.resolver(kwargs, result, timer.elapsed)
                    if trace is not None:
                        run.log({"trace": trace})
                    return result

                return create

            # save original method
            self.original_methods[symbol] = original
            # monkeypatch
            getattr(openai, symbol).create = method_factory(original)

    def unpatch(self):
        for symbol, original in self.original_methods.items():
            getattr(openai, symbol).create = original


class AutologOpenAI:
    def __init__(self):
        self.patch_openai_api = PatchOpenAIAPI()
        self.run: Optional["wandb.sdk.wandb_run.Run"] = None

    def enable(self, project: str):
        self.run = wandb.init(project=project)
        self.patch_openai_api.patch(self.run)

    def disable(self):
        self.run.finish()
        self.patch_openai_api.unpatch()
