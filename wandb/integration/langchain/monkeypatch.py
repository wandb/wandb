"""This file is responsible for monkeypatching langchain to get data out for W&B logging.

Currently it's main responsibility is to ensure that the `on_[model]_start`
callbacks include the model that is being started. This is done by making a
general callback proxy and overriding the init method of the models to wrap the
callback manager with the proxy. Also, we ensure that all chains are
serializable by overriding the `Chain._chain_type` property to return the class
name of the chain.

The more we work with langChain, the smaller this file should get. Ideally this
goes away entirely.
"""

import inspect
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from langchain.callbacks.base import BaseCallbackManager
    from langchain.chains.base import Chain
    from langchain.llms.base import BaseLLM
    from langchain.tools.base import BaseTool

patched_symbols = {}


def ensure_patched():
    for patch_method in [
        _patch_chain_type,
        _patch_single_agent_type,
        _patch_multi_agent_type,
        _patch_llm_type,
        _patch_prompt_type,
        _patch_output_parser_type,
        _patch_chain_init,
        _patch_llm_init,
        _patch_tool_init,
    ]:
        try:
            patch_method()
        except Exception:
            pass


def clear_patches():
    for clear_method in [
        _clear_chain_type,
        _clear_single_agent_type,
        _clear_multi_agent_type,
        _clear_llm_type,
        _clear_prompt_type,
        _clear_output_parser_type,
        _clear_chain_init,
        _clear_llm_init,
        _clear_tool_init,
    ]:
        try:
            clear_method()
        except Exception:
            pass


def _patch_chain_type():
    from langchain.chains.base import Chain

    if "Chain._chain_type" in patched_symbols:
        return
    patched_symbols["Chain._chain_type"] = Chain._chain_type

    def _chain_type(self) -> str:
        return self.__class__.__name__

    Chain._chain_type = property(_chain_type)


def _clear_chain_type():
    from langchain.chains.base import Chain

    if "Chain._chain_type" not in patched_symbols:
        return
    Chain._chain_type = patched_symbols["Chain._chain_type"]
    del patched_symbols["Chain._chain_type"]


def _patch_single_agent_type():
    from langchain.agents.agent import BaseSingleActionAgent

    if "BaseSingleActionAgent._agent_type" in patched_symbols:
        return

    patched_symbols[
        "BaseSingleActionAgent._agent_type"
    ] = BaseSingleActionAgent._agent_type

    def _agent_type(self) -> str:
        return self.__class__.__name__

    BaseSingleActionAgent._agent_type = property(_agent_type)


def _clear_single_agent_type():
    from langchain.agents.agent import BaseSingleActionAgent

    if "BaseSingleActionAgent._agent_type" not in patched_symbols:
        return
    BaseSingleActionAgent._agent_type = patched_symbols[
        "BaseSingleActionAgent._agent_type"
    ]
    del patched_symbols["BaseSingleActionAgent._agent_type"]


def _patch_multi_agent_type():
    from langchain.agents.agent import BaseMultiActionAgent

    if "BaseMultiActionAgent._agent_type" in patched_symbols:
        return

    patched_symbols[
        "BaseMultiActionAgent._agent_type"
    ] = BaseMultiActionAgent._agent_type

    def _agent_type(self) -> str:
        return self.__class__.__name__

    BaseMultiActionAgent._agent_type = property(_agent_type)


def _clear_multi_agent_type():
    from langchain.agents.agent import BaseMultiActionAgent

    if "BaseMultiActionAgent._agent_type" not in patched_symbols:
        return
    BaseMultiActionAgent._agent_type = patched_symbols[
        "BaseMultiActionAgent._agent_type"
    ]
    del patched_symbols["BaseMultiActionAgent._agent_type"]


def _patch_llm_type():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._llm_type" in patched_symbols:
        return

    patched_symbols["BaseLLM._llm_type"] = BaseLLM._llm_type

    def _llm_type(self) -> str:
        return self.__class__.__name__

    BaseLLM._llm_type = property(_llm_type)


def _clear_llm_type():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._llm_type" not in patched_symbols:
        return
    BaseLLM._llm_type = patched_symbols["BaseLLM._llm_type"]
    del patched_symbols["BaseLLM._llm_type"]


def _patch_output_parser_type():
    from langchain.schema import BaseOutputParser

    if "BaseOutputParser._type" in patched_symbols:
        return

    patched_symbols["BaseOutputParser._type"] = BaseOutputParser._type

    def _type(self) -> str:
        return self.__class__.__name__

    BaseOutputParser._type = property(_type)


def _clear_output_parser_type():
    from langchain.schema import BaseOutputParser

    if "BaseOutputParser._type" not in patched_symbols:
        return
    BaseOutputParser._type = patched_symbols["BaseOutputParser._type"]
    del patched_symbols["BaseOutputParser._type"]


def _patch_prompt_type():
    from langchain.prompts.base import BasePromptTemplate

    if "BasePromptTemplate._prompt_type" in patched_symbols:
        return

    patched_symbols["BasePromptTemplate._prompt_type"] = BasePromptTemplate._prompt_type

    def _prompt_type(self) -> str:
        return self.__class__.__name__

    BasePromptTemplate._prompt_type = property(_prompt_type)


def _clear_prompt_type():
    from langchain.prompts.base import BasePromptTemplate

    if "BasePromptTemplate._prompt_type" not in patched_symbols:
        return
    BasePromptTemplate._prompt_type = patched_symbols["BasePromptTemplate._prompt_type"]
    del patched_symbols["BasePromptTemplate._prompt_type"]


def _patch_chain_init():
    from langchain.chains.base import Chain

    if "Chain._init__" in patched_symbols:
        return

    patched_symbols["Chain._init__"] = Chain.__init__

    _wrap_init(Chain)


def _clear_chain_init():
    from langchain.chains.base import Chain

    if "Chain._init__" not in patched_symbols:
        return
    Chain.__init__ = patched_symbols["Chain._init__"]
    del patched_symbols["Chain._init__"]


def _patch_llm_init():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._init__" in patched_symbols:
        return

    patched_symbols["BaseLLM._init__"] = BaseLLM.__init__

    _wrap_init(BaseLLM)


def _clear_llm_init():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._init__" not in patched_symbols:
        return
    BaseLLM.__init__ = patched_symbols["BaseLLM._init__"]
    del patched_symbols["BaseLLM._init__"]


def _patch_tool_init():
    from langchain.tools.base import BaseTool

    if "BaseTool._init__" in patched_symbols:
        return

    patched_symbols["BaseTool._init__"] = BaseTool.__init__

    _wrap_init(BaseTool)


def _clear_tool_init():
    from langchain.tools.base import BaseTool

    if "BaseTool._init__" not in patched_symbols:
        return
    BaseTool.__init__ = patched_symbols["BaseTool._init__"]
    del patched_symbols["BaseTool._init__"]


def _wrap_init(cls):
    current_init = None
    if hasattr(cls, "__init__"):
        current_init = cls.__init__

    def init(self, *args, **kwargs):
        if current_init:
            try:
                if "callback_manager" in kwargs and isinstance(
                    kwargs["callback_manager"], _CallbackManagerOnStartProxy
                ):
                    kwargs["callback_manager"] = kwargs[
                        "callback_manager"
                    ]._internal_callback_manager
            except Exception:
                pass
            current_init(self, *args, **kwargs)
        self.callback_manager = _CallbackManagerOnStartProxy(
            self.callback_manager, self
        )

    cls.__init__ = init


class _CallbackManagerOnStartProxy:
    _internal_callback_manager: "BaseCallbackManager"
    _bound_model: Union["BaseLLM", "BaseTool", "Chain"]

    def __init__(
        self, callback_manager: "BaseCallbackManager", bound_model=None
    ) -> None:
        self._internal_callback_manager = callback_manager
        self._bound_model = bound_model

    def __getattr__(self, name: str) -> Any:
        if name == "_internal_callback_manager":
            return self.__dict__["_internal_callback_manager"]
        elif name == "_bound_model":
            return self.__dict__["_bound_model"]

        return getattr(self.__dict__["_internal_callback_manager"], name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_internal_callback_manager":
            self.__dict__["_internal_callback_manager"] = value
        elif name == "_bound_model":
            self.__dict__["_bound_model"] = value
        setattr(self._internal_callback_manager, name, value)

    def _handle_proxied_call(self, cb_name: str, *args, **kwargs) -> None:
        method = getattr(self._internal_callback_manager, cb_name)
        try:
            sig = inspect.signature(method)
            bound_kwargs = sig.bind(*args, **kwargs).arguments
            serialized = bound_kwargs.get("serialized", {})
            serialized["_self"] = self._bound_model
            bound_kwargs["serialized"] = serialized
            args = []
            kwargs = bound_kwargs
        except Exception:
            pass
        method(*args, **kwargs)

    def on_llm_start(self, *args, **kwargs) -> None:
        self._handle_proxied_call("on_llm_start", *args, **kwargs)

    def on_chain_start(self, *args, **kwargs) -> None:
        self._handle_proxied_call("on_chain_start", *args, **kwargs)

    def on_tool_start(self, *args, **kwargs) -> None:
        self._handle_proxied_call("on_tool_start", *args, **kwargs)
