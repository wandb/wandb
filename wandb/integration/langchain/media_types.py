import json
import logging
import typing

if typing.TYPE_CHECKING:
    from langchain.agents import Agent
    from langchain.callbacks.tracers.schemas import ChainRun, LLMRun, ToolRun
    from langchain.chains.base import Chain
    from langchain.chat_models.base import BaseChatModel
    from langchain.llms import BaseLLM

import wandb
from wandb.data_types import _json_helper
from wandb.sdk.data_types import _dtypes
from wandb.sdk.data_types.base_types.media import Media
    import hashlib


# generate a deterministic 16 character id based on input string
def _hash_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def rewrite_url(run_url: str) -> str:
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


def print_wandb_init_message(run_url: str) -> None:
    run_url = rewrite_url(run_url)
    wandb.termlog(

            f"W&B Run initialized. View LangChain logs in W&B at {run_url}. "
            "\n\nNote that the "
            "WandbTracer is currently in beta and is subject to change "
            "based on updates to `langchain`. Please report any issues to "
            "https://github.com/wandb/wandb/issues with the tag `langchain`."

    )


def print_wandb_finish_message(run_url: str) -> None:
    run_url = rewrite_url(run_url)
    wandb.termlog(f"All files uploaded. View LangChain logs in W&B at {run_url}.")


def safe_serialize(obj):
    return json.dumps(
        _json_helper(obj, None),
        skipkeys=True,
        default=lambda o: f"<<non-serializable: {type(o).__qualname__}>>",
    )


class LangChainModelTrace(Media):
    _log_type = "langchain_model_trace"

    def __init__(
        self,
        trace: typing.Union["LLMRun", "ChainRun", "ToolRun"],
        model: typing.Union["BaseLLM", "BaseChatModel", "Chain", "Agent", None] = None,
    ):
        super().__init__()
        self._trace = trace
        self._model = model
        self._model_dict = None
        self._trace_dict = None

    @classmethod
    def get_media_subdir(cls) -> str:
        return "media/langchain_model_trace"

    @property
    def model_dict(self):
        if self._model is None:
            return {}
        if self._model_dict is None:
            data = None

            try:
                data = self._model.dict()
            except NotImplementedError:
                pass

            if data is None and hasattr(self._model, "agent"):
                try:
                    data = self._model.agent.dict()
                except NotImplementedError:
                    pass

            if data is None:
                logging.warning("Could not get model data.")
                data = {}

            self._model_dict = data
        return self._model_dict

    @property
    def trace_dict(self):
        if self._trace_dict is None:
            try:
                self._trace_dict = self._trace.dict()
            except Exception as e:
                logging.warning(f"Could not get trace data: {e}")
                self._trace_dict = {}
        return self._trace_dict

    def to_json(self, run) -> dict:
        res = {}
        res["_type"] = self._log_type
        model_dict_str = safe_serialize(self.model_dict)
        res["model_id"] = _hash_id(model_dict_str)
        res["model_dict"] = json.loads(model_dict_str)
        res["trace_dict"] = json.loads(safe_serialize(self.trace_dict))
        return res

    def is_bound(self) -> bool:
        return True


class _LangChainModelTraceFileType(_dtypes.Type):
    name = "langchain_model_trace"
    types = [LangChainModelTrace]


_dtypes.TypeRegistry.add(_LangChainModelTraceFileType)
