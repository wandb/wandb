import json
import logging
import os
import typing

if typing.TYPE_CHECKING:
    from langchain.llms import BaseLLM
    from langchain.chat_models.base import BaseChatModel
    from langchain.chains.base import Chain
    from langchain.agents import Agent
    from langchain.callbacks.tracers.schemas import (
        ChainRun,
        LLMRun,
        ToolRun,
    )

from wandb.sdk.data_types.base_types.media import Media
from wandb.data_types import _json_helper, MEDIA_TMP
from wandb.sdk.data_types import _dtypes
from wandb.sdk.lib.runid import generate_id

# # Generate a deterministic 16 character string from a dictionary
# def _generate_id_from_dict(d: dict) -> str:
#     import hashlib
#     import json
#     import base64

#     return base64.b16encode(hashlib.sha256(json.dumps(d).encode()).digest()).decode()[
#         :16
#     ]


def safe_serialize(obj):
    return json.dumps(
        _json_helper(obj, None),
        skipkeys=True,
        default=lambda o: f"<<non-serializable: {type(o).__qualname__}>>",
    )


class LangChainModel(Media):
    _log_type = "langchain_model-file"

    def __init__(
        self, model: typing.Union["BaseLLM", "BaseChatModel", "Chain", "Agent"]
    ):
        super().__init__()
        self._model_data = None
        self._model_id = None
        self._model = model
        tmp_path = os.path.join(MEDIA_TMP.name, generate_id() + ".json")
        self.format = "json"
        with open(tmp_path, "w") as f:
            f.write(safe_serialize(self.model_data))
        self._set_file(tmp_path, is_tmp=True)

    def get_media_subdir(cls) -> str:
        return "media/langchain_model-file"

    def to_json(self, run) -> dict:
        res = super().to_json(run)
        res["_type"] = self._log_type
        return res

    @property
    def model_data(self):
        if self._model_data is None:
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

            self._model_data = data
        return self._model_data

    # @property
    # def model_id(self) -> str:
    #     if self._model_id is None:
    #         self._model_id = _generate_id_from_dict(_json_helper(self.model_data, None))
    #     return self._model_id


class _LangChainModelFileType(_dtypes.Type):
    name = "langchain_model-file"
    types = [LangChainModel]


_dtypes.TypeRegistry.add(_LangChainModelFileType)


class LangChainTrace(Media):
    _log_type = "langchain_trace"

    def __init__(self, run: typing.Union["LLMRun", "ChainRun", "ToolRun"]):
        super().__init__()
        self._run = run

    def get_media_subdir(cls) -> str:
        return "media/langchain_trace"

    def to_json(self, run) -> dict:
        res = super().to_json(run)
        res["_type"] = self._log_type
        # Ugg... this is so nasty
        res["data"] = json.loads(safe_serialize(self._run.dict()))
        return res


class _LangChainTraceFileType(_dtypes.Type):
    name = "langchain_trace"
    types = [LangChainTrace]


_dtypes.TypeRegistry.add(_LangChainTraceFileType)
