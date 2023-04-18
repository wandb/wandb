import logging
import sys
from typing import Any, Dict, List, Optional, TypeVar

from wandb.sdk.data_types import trace_tree

if sys.version_info >= (3, 8):
    from typing import Literal, Protocol
else:
    from typing_extensions import Literal, Protocol


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
            request: The request dictionary
            response: The response object
            results: A list of results object
            time_elapsed: The time elapsed in seconds
        returns:
            A wandb trace tree object.
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
        """Resolves the request and response objects for `openai.Edit`."""

        def format_request(_request: Dict[str, Any]) -> str:
            """Formats the request object to a string.

            params:
                request: The request dictionary
                response: The response object
            returns:
                A string representation of the request object to be logged
            """
            prompt = (
                f"\n\n**Instruction**: {_request['instruction']}\n\n"
                f"**Input**: {_request['input']}\n"
            )
            return prompt

        def format_response_choice(_choice: Dict[str, Any]) -> str:
            """Formats the choice in a response object to a string.

            params:
                choice: The choice dictionary
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
