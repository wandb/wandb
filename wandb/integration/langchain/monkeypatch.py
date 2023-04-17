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
from typing import Any, Union

from langchain.callbacks.base import BaseCallbackManager
from langchain.chains.base import Chain
from langchain.chat_models.base import BaseChatModel
from langchain.llms.base import BaseLLM
from langchain.tools.base import BaseTool

_IS_PATCHED = False
original_symbols = {}


def ensure_patched():
    global _IS_PATCHED
    if _IS_PATCHED:
        return
    _IS_PATCHED = True
    try:
        original_symbols["_chain_chain_type"] = Chain._chain_type
        original_symbols["chain_init"] = Chain.__init__
        original_symbols["llm_init"] = BaseLLM.__init__
        original_symbols["tool_init"] = BaseTool.__init__
        original_symbols["chat_model_init"] = BaseChatModel.__init__
        Chain._chain_type = property(_chain_type)
        _wrap_init(Chain)
        _wrap_init(BaseLLM)
        _wrap_init(BaseTool)
        _wrap_init(BaseChatModel)
    except Exception:
        # This monkey patch failure will result in models not saving,
        # but it's not a fatal error.
        pass


def clear_patches():
    global _IS_PATCHED
    if not _IS_PATCHED:
        return
    _IS_PATCHED = False
    try:
        Chain._chain_type = original_symbols["_chain_chain_type"]
        Chain.__init__ = original_symbols["chain_init"]
        BaseLLM.__init__ = original_symbols["llm_init"]
        BaseTool.__init__ = original_symbols["tool_init"]
        BaseChatModel.__init__ = original_symbols["chat_model_init"]
    except Exception:
        # This monkey patch failure will result in models not saving,
        # but it's not a fatal error.
        pass


class _CallbackManagerOnStartProxy:
    _internal_callback_manager: BaseCallbackManager
    _bound_model: Union[BaseLLM, BaseTool, Chain]

    def __init__(self, callback_manager: BaseCallbackManager, bound_model=None) -> None:
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


def _chain_type(self) -> str:
    return self.__class__.__name__


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
