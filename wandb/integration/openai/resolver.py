import datetime
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import wandb
from wandb.sdk.data_types import trace_tree
from wandb.sdk.integration_utils.auto_logging import OpenAIResponse, Response
from wandb.util import check_openai_version_is_major_version

logger = logging.getLogger(__name__)


@dataclass
class UsageMetrics:
    elapsed_time: float = None
    prompt_tokens: int = None
    completion_tokens: int = None
    total_tokens: int = None


@dataclass
class Metrics:
    usage: UsageMetrics = None
    stats: wandb.Table = None
    trace: trace_tree.WBTraceTree = None


usage_metric_keys = {f"usage/{k}" for k in asdict(UsageMetrics())}


def get_openai_object(
    response: Response, key: str, is_major_version: bool, default=None
) -> Any:
    if is_major_version:
        try:
            return getattr(response, key)
        except Exception:
            logger.warning("Failed to get object from response: {e}")
            return default
    else:
        try:
            return response.get(key, default)
        except Exception as e:
            logger.warning("Failed to get object from response: {e}")
            raise ValueError(f"Failed to get object from response: {e}")


def serialize(obj):
    """Serialize the complex object recursively into dict, list, and basic types."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, dict):
        return {key: serialize(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [serialize(item) for item in obj]
    elif hasattr(obj, "__dict__"):
        return {key: serialize(value) for key, value in obj.__dict__.items()}
    else:
        return str(obj)


class OpenAIRequestResponseResolver:
    def __init__(self, is_major_version: bool = False):
        self.define_metrics_called = False
        self.is_major_version: bool = is_major_version

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,  # pass to comply with the protocol, but use response["created"] instead
        time_elapsed: float,
    ) -> Optional[Dict[str, Any]]:
        request = kwargs

        if not self.define_metrics_called:
            # define metrics on first call
            for key in usage_metric_keys:
                wandb.define_metric(key, step_metric="_timestamp")
            self.define_metrics_called = True

        try:
            response_object = get_openai_object(
                response, "object", self.is_major_version
            )
            if response_object == "edit":
                return self._resolve_edit(request, response, time_elapsed)
            elif response_object == "text_completion":
                return self._resolve_completion(request, response, time_elapsed)
            elif response_object == "chat.completion":
                return self._resolve_chat_completion(request, response, time_elapsed)
            else:
                # todo: properly treat failed requests
                logger.info(f"Unsupported OpenAI response object: {response_object}")
        except Exception as e:
            logger.warning(f"Failed to resolve request/response: {e}")
        return None

    @staticmethod
    def results_to_trace_tree(
        request: Dict[str, Any],
        response: Response | OpenAIResponse,
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
        is_major_version = check_openai_version_is_major_version()
        created = get_openai_object(response, "created", is_major_version)
        start_time_ms = int(round(created * 1000))
        end_time_ms = start_time_ms + int(round(time_elapsed * 1000))
        openai_model = get_openai_object(
            response,
            "model",
            is_major_version,
            "openai",
        )
        openai_object = get_openai_object(response, "object", is_major_version)

        if is_major_version:
            serialized_response = serialize(response)
        else:
            serialized_response = dict(response)

        span = trace_tree.Span(
            name=f"{openai_model}_{openai_object}_{created}",
            attributes=serialized_response,  # type: ignore
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            span_kind=trace_tree.SpanKind.LLM,
            results=results,
        )
        model_obj = {
            "request": request,
            "response": serialized_response,
            "_kind": "openai",
        }
        return trace_tree.WBTraceTree(root_span=span, model_dict=model_obj)

    def _resolve_edit(
        self,
        request: Dict[str, Any],
        response: Response,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Edit`.

        Deprecated in openai major version, 2024-01-04.
        """
        request_str = (
            f"\n\n**Instruction**: {request['instruction']}\n\n"
            f"**Input**: {request['input']}\n"
        )
        choices = [
            f"\n\n**Edited**: {choice['text']}\n" for choice in response["choices"]
        ]

        return self._resolve_metrics(
            request=request,
            response=response,
            request_str=request_str,
            choices=choices,
            time_elapsed=time_elapsed,
        )

    def _resolve_completion(
        self,
        request: Dict[str, Any],
        response: Response | OpenAIResponse,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion` and `openai.resources.completions."""
        request_str = f"\n\n**Prompt**: {request['prompt']}\n"
        if self.is_major_version:
            choices = [
                f"\n\n**Completion**: {choice.text}\n" for choice in response.choices
            ]
        else:
            choices = [
                f"\n\n**Completion**: {choice['text']}\n"
                for choice in response["choices"]
            ]

        return self._resolve_metrics(
            request=request,
            response=response,
            request_str=request_str,
            choices=choices,
            time_elapsed=time_elapsed,
        )

    def _resolve_chat_completion(
        self,
        request: Dict[str, Any],
        response: Response | OpenAIResponse,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion` and `openai.resources.chat.completions."""
        request_str = request["messages"]

        if self.is_major_version:
            choices = [
                f"\n\n{choice.message.role}: {choice.message.content}\n"
                for choice in response.choices
            ]
        else:
            choices = [
                f"\n\n{choice['message']['role']}: {choice['message']['content']}\n"
                for choice in response["choices"]
            ]

        return self._resolve_metrics(
            request=request,
            response=response,
            request_str=request_str,
            choices=choices,
            time_elapsed=time_elapsed,
        )

    def _resolve_metrics(
        self,
        request: Dict[str, Any],
        response: Response | OpenAIResponse,
        request_str: str,
        choices: List[str],
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion` and `openai.resources.completions."""
        if self.is_major_version:
            choices = [serialize(choice) for choice in response.choices]
        results = [
            trace_tree.Result(
                inputs={"request": request_str},
                outputs={"response": choice},
            )
            for choice in choices
        ]
        metrics = self._get_metrics_to_log(request, response, results, time_elapsed)
        return self._convert_metrics_to_dict(metrics)

    @staticmethod
    def _get_usage_metrics(response: Response, time_elapsed: float) -> UsageMetrics:
        """Gets the usage stats from the response object."""
        is_major_version = check_openai_version_is_major_version()
        usage = get_openai_object(response, "usage", is_major_version)
        if usage:
            if is_major_version:
                # The major version of openai doesn't return usage as a dictionary.
                usage_stats = UsageMetrics(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
            else:
                usage_stats = UsageMetrics(**usage)
        else:
            usage_stats = UsageMetrics()
        usage_stats.elapsed_time = time_elapsed
        return usage_stats

    def _get_metrics_to_log(
        self,
        request: Dict[str, Any],
        response: Response,
        results: List[Any],
        time_elapsed: float,
    ) -> Metrics:
        model = get_openai_object(
            response, "model", self.is_major_version
        ) or request.get("model")
        usage_metrics = self._get_usage_metrics(response, time_elapsed)
        created = get_openai_object(response, "created", self.is_major_version)

        usage = []
        for result in results:
            row = {
                "request": request,
                "response": result.outputs["response"],
                "model": model,
                "start_time": datetime.datetime.fromtimestamp(created),
                "end_time": datetime.datetime.fromtimestamp(created + time_elapsed),
                "request_id": get_openai_object(response, "id", self.is_major_version),
                "api_type": get_openai_object(
                    response, "api_type", self.is_major_version, "openai"
                ),
                "session_id": wandb.run.id,
            }
            row.update(asdict(usage_metrics))
            usage.append(row)
        usage_table = wandb.Table(
            columns=list(usage[0].keys()),
            data=[(item.values()) for item in usage],
        )

        trace = self.results_to_trace_tree(request, response, results, time_elapsed)

        metrics = Metrics(stats=usage_table, trace=trace, usage=usage_metrics)
        return metrics

    @staticmethod
    def _convert_metrics_to_dict(metrics: Metrics) -> Dict[str, Any]:
        """Converts metrics to a dict."""
        metrics_dict = {
            "stats": metrics.stats,
            "trace": metrics.trace,
        }
        usage_stats = {f"usage/{k}": v for k, v in asdict(metrics.usage).items()}
        metrics_dict.update(usage_stats)
        return metrics_dict
