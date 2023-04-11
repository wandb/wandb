# TODO:
# - Figure out how to deduplicate model data

import json
import typing

from .schema import BaseRunSpan

import wandb
from wandb.data_types import _json_helper
from wandb.sdk.data_types import _dtypes
from wandb.sdk.data_types.base_types.media import Media
import hashlib


def print_wandb_init_message(run_url: str) -> None:
    run_url = _rewrite_url(run_url)
    wandb.termlog(
        f"W&B Run initialized. View LangChain logs in W&B at {run_url}. "
        "\n\nNote that the "
        "WandbTracer is currently in beta and is subject to change "
        "based on updates to `langchain`. Please report any issues to "
        "https://github.com/wandb/wandb/issues with the tag `langchain`."
    )


def print_wandb_finish_message(run_url: str) -> None:
    run_url = _rewrite_url(run_url)
    wandb.termlog(f"All files uploaded. View LangChain logs in W&B at {run_url}.")


class LangChainModelTrace(Media):
    _log_type = "langchain_model_trace"

    def __init__(
        self,
        trace_dict: BaseRunSpan,
        model_dict: typing.Optional[dict] = None,
    ):
        super().__init__()
        self._trace_dict = trace_dict
        # NOTE: model_dict is a completely-user-defined dict. In the UI
        # we simply render a JSON tree view and give special UI treatment to
        # dictionaries with a _type key. If that _type key has "prompt", "chain"
        # or "agent", then we render a special UI for that model. Unfortunately,
        # this is because Models are completely user-defined classes and we cannot
        # control or validate any specific schema. In the future, we can work
        # with the LangChain team to define a schema for these models.

        self._model_dict = model_dict

    @classmethod
    def get_media_subdir(cls) -> str:
        return "media/langchain_model_trace"

    def to_json(self, run) -> dict:
        res = {}
        res["_type"] = self._log_type
        model_dict_str = _safe_serialize(self.model_dict)
        res["model_hash"] = _hash_id(model_dict_str)
        res["model_dict"] = json.loads(model_dict_str)
        res["trace_dict"] = _json_helper(self.trace_dict, None)
        return res

    def is_bound(self) -> bool:
        return True


class _LangChainModelTraceFileType(_dtypes.Type):
    name = "langchain_model_trace"
    types = [LangChainModelTrace]


_dtypes.TypeRegistry.add(_LangChainModelTraceFileType)


# generate a deterministic 16 character id based on input string
def _hash_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def _rewrite_url(run_url: str) -> str:
    old_prefix = "https://wandb.ai/"
    new_prefix = "https://beta.wandb.ai/"
    new_suffix = "betaVersion=711cc17ffb2b90cd733d4a87905fcf21f984acfe"
    if run_url.startswith(old_prefix):
        run_url = run_url.replace(old_prefix, new_prefix, 1)
        if "?" in run_url:
            run_url = run_url.replace("?", f"?{new_suffix}&", 1)
        else:
            run_url = f"{run_url}?{new_suffix}"
    return run_url


def _safe_serialize(obj):
    return json.dumps(
        _json_helper(obj, None),
        skipkeys=True,
        default=lambda o: f"<<non-serializable: {type(o).__qualname__}>>",
    )
