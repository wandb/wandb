import io
import logging
import uuid
from typing import Any, Dict, List, Optional

import wandb
from wandb.sdk.data_types import trace_tree
from wandb.sdk.integration_utils.llm import Response

logger = logging.getLogger(__name__)
from dataclasses import asdict, dataclass


def get_model_alias(model_name: str, is_completion: bool = False) -> Dict[str, str]:
    alias_cost_mapping = {
        "gpt-4": {
            "alias": "gpt-4",
        },
        "gpt-4-0314": {
            "alias": "gpt-4",
        },
        "gpt-4-completion": {
            "alias": "gpt-4",
        },
        "gpt-4-0314-completion": {
            "alias": "gpt-4",
        },
        "gpt-4-32k": {
            "alias": "gpt-4",
        },
        "gpt-4-32k-0314": {
            "alias": "gpt-4",
        },
        "gpt-4-32k-completion": {
            "alias": "gpt-4",
        },
        "gpt-4-32k-0314-completion": {
            "alias": "gpt-4",
        },
        "gpt-3.5-turbo": {
            "alias": "gpt-3.5",
        },
        "gpt-3.5-turbo-0301": {
            "alias": "gpt-3.5",
        },
        "text-ada-001": {
            "alias": "gpt-3",
        },
        "ada": {
            "alias": "gpt-3",
        },
        "text-babbage-001": {
            "alias": "gpt-3",
        },
        "babbage": {
            "alias": "gpt-3",
        },
        "text-curie-001": {
            "alias": "gpt-3",
        },
        "curie": {
            "alias": "gpt-3",
        },
        "text-davinci-003": {
            "alias": "gpt-3",
        },
        "text-davinci-edit-001": {
            "alias": "gpt-3",
        },
        "code-davinci-edit-001": {
            "alias": "gpt-3",
        },
        "text-davinci-002": {
            "alias": "gpt-3",
        },
        "code-davinci-002": {
            "alias": "gpt-3",
        },
    }

    alias_cost = alias_cost_mapping.get(
        model_name.lower()
        + ("-completion" if is_completion and model_name.startswith("gpt-4") else ""),
        None,
    )
    return alias_cost


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


class OpenAIRequestResponseResolver:
    def __call__(
        self,
        request: Dict[str, Any],
        response: Response,
        start_time: float,  # pass to comply with the protocol, but use response["created"] instead
        time_elapsed: float,
    ) -> Optional[Dict[str, Any]]:
        try:
            if response.get("object") == "edit":
                return self._resolve_edit(request, response, time_elapsed)
            elif response.get("object") == "text_completion":
                return self._resolve_completion(request, response, time_elapsed)
            elif response.get("object") == "chat.completion":
                return self._resolve_chat_completion(request, response, time_elapsed)
            else:
                logger.info(
                    f"Unsupported OpenAI response object: {response.get('object')}"
                )
        except Exception as e:
            logger.warning(f"Failed to resolve request/response: {e}")
        return None

    @staticmethod
    def results_to_trace_tree(
        request: Dict[str, Any],
        response: Response,
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
        response: Response,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Edit`."""
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
        response: Response,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion`."""
        request_str = f"\n\n**Prompt**: {request['prompt']}\n"
        choices = [
            f"\n\n**Completion**: {choice['text']}\n" for choice in response["choices"]
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
        response: Response,
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion`."""
        prompt = io.StringIO()
        for message in request["messages"]:
            prompt.write(f"\n\n**{message['role']}**: {message['content']}\n")
        request_str = prompt.getvalue()

        choices = [
            f"\n\n**{choice['message']['role']}**: {choice['message']['content']}\n"
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
        response: Response,
        request_str: str,
        choices: List[str],
        time_elapsed: float,
    ) -> Dict[str, Any]:
        """Resolves the request and response objects for `openai.Completion`."""
        results = [
            trace_tree.Result(
                inputs={"request": request_str},
                outputs={"response": choice},
            )
            for choice in choices
        ]
        metrics = self._get_metrics_to_log(request, response, results, time_elapsed)
        metrics = self._convert_metrics_to_dict(metrics)
        return metrics

    def _get_usage_metrics(
        self,
        response: Response,
        time_elapsed: float,
    ) -> UsageMetrics:
        """Gets the usage stats from the response object."""
        if response.get("usage"):
            usage_stats = UsageMetrics(**response["usage"])
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
        if response["object"] in ("text_completion", "chat.completion"):
            is_completion = True
        else:
            is_completion = False
        model = response.get("model") or request.get("model")
        if model:
            model_alias = get_model_alias(model.lower(), is_completion=is_completion)
        else:
            model_alias = None

        model_alias = model_alias["alias"] if model_alias else None

        usage_metrics = self._get_usage_metrics(response, time_elapsed)

        usage_table = []
        for result in results:
            row = {
                "request": result.inputs["request"],
                "response": result.outputs["response"],
                "model_alias": model_alias,
                "model": model,
                "start_time": response["created"],
                "end_time": response["created"] + time_elapsed,
                "request_id": response["id"]
                if response.get("id")
                else str(uuid.uuid4()),
                "session_id": wandb.run.id,
            }
            row.update(asdict(usage_metrics))
            usage_table.append(row)
        usage_table = wandb.Table(
            columns=list(usage_table[0].keys()),
            data=[(item.values()) for item in usage_table],
        )

        trace = self.results_to_trace_tree(request, response, results, time_elapsed)

        stats = usage_table
        metrics = Metrics(stats=stats, trace=trace, usage=usage_metrics)
        return metrics

    def _convert_metrics_to_dict(self, metrics: Metrics):
        """Converts metrics to a dict."""
        metrics_dict = {}
        metrics_dict["stats"] = metrics.stats
        metrics_dict["trace"] = metrics.trace
        usage_stats = {f"usage/{k}": v for k, v in asdict(metrics.usage).items()}
        for key in usage_stats:
            wandb.define_metric(key, step_metric="_timestamp")
        metrics_dict.update(usage_stats)
        return metrics_dict
