import logging
from typing import Any, Dict, List, Optional

from wandb.sdk.data_types import trace_tree
from wandb.sdk.integration_utils.llm import Response

logger = logging.getLogger(__name__)


class CohereRequestResponseResolver:
    def __call__(
        self,
        request: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Optional[trace_tree.WBTraceTree]:
        try:
            if hasattr(response, "generations"):
                return self._resolve_generate(
                    request, response, start_time, time_elapsed
                )
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
        response: Dict[str, Any],
        endpoint: str,
        results: List[trace_tree.Result],
        start_time: float,
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
        start_time_ms = int(round(start_time * 1000))
        end_time_ms = start_time_ms + int(round(time_elapsed * 1000))
        span = trace_tree.Span(
            name=f"cohere_{endpoint}_{start_time_ms}",
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
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        """Resolves the request and response objects for `cohere.Client.generate`."""
        request_str = f"\n\n**Prompt**: {request['prompt']}\n"
        choices = [f"\n\n**Generation**: {choice.text}\n" for choice in response]

        return self._request_response_result_to_trace(
            request=request,
            # response=response,
            response={"generations": [g.__dict__ for g in response]},
            endpoint="generate",
            request_str=request_str,
            choices=choices,
            start_time=start_time,
            time_elapsed=time_elapsed,
        )

    def _request_response_result_to_trace(
        self,
        request: Dict[str, Any],
        response: Dict[str, Any],
        endpoint: str,
        request_str: str,
        choices: List[str],
        start_time: float,
        time_elapsed: float,
    ) -> trace_tree.WBTraceTree:
        """Resolves the request and response objects for `cohere.Client`."""
        # breakpoint()
        results = [
            trace_tree.Result(
                inputs={"request": request_str},
                outputs={"response": choice},
            )
            for choice in choices
        ]
        trace = self.results_to_trace_tree(
            request, response, endpoint, results, start_time, time_elapsed
        )
        return trace
