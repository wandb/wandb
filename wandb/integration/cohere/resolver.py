import io
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


class CohereResponse(Protocol[K, V]):
    def __getitem__(self, key: K) -> V:
        ...  # pragma: no cover

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        ...  # pragma: no cover


class CohereRequestResponseResolver:
    def __call__(
        self,
        request: Dict[str, Any],
        response: CohereResponse,
        time_elapsed: float,
    ) -> Optional[trace_tree.WBTraceTree]:
        try:
            if hasattr(response, "generations"):
                return self._resolve_generate(request, response, time_elapsed)
            # elif hasattr(response, "chatlog"):
            #     return self._resolve_chat(request, response, time_elapsed)
            else:
                logger.info(f"Unsupported Cohere response object: {response}")
        except Exception as e:
            logger.warning(f"Failed to resolve request/response: {e}")
        return None

    @staticmethod
    def results_to_trace_tree(
        request: Dict[str, Any],
        response: CohereResponse,
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
        # start_time_ms = int(round(response["created"] * 1000))
        start_time_ms = 0
        end_time_ms = start_time_ms + int(round(time_elapsed * 1000))
        span = trace_tree.Span(
            name=f"cohere_{response.__class__.__name__}_{response.get('id')}",
            attributes=dict(response),  # type: ignore
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            span_kind=trace_tree.SpanKind.LLM,
            results=results,
        )
        model_obj = {"request": request, "response": response, "_kind": "cohere"}
        return trace_tree.WBTraceTree(root_span=span, model_dict=model_obj)

    def _resolve_generate(
        self,
        request: Dict[str, Any],
        response: CohereResponse,
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        """Resolves the request and response objects for `cohere.Client.generate`."""
        request_str = f"\n\n**Query**: {request['query']}\n"
        choices = [
            f"\n\n**Response**: {response['text']}\n"
        ]

        return self._request_response_result_to_trace(
            request=request,
            response=response,
            request_str=request_str,
            choices=choices,
            time_elapsed=time_elapsed,
        )

    def _request_response_result_to_trace(
        self,
        request: Dict[str, Any],
        response: CohereResponse,
        request_str: str,
        choices: List[str],
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        """Resolves the request and response objects for `cohere.Client`."""
        results = [
            trace_tree.Result(
                inputs={"request": request_str},
                outputs={"response": choice},
            )
            for choice in choices
        ]
        trace = self.results_to_trace_tree(request, response, results, time_elapsed)
        return trace
