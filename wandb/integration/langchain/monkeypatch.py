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
from typing import TYPE_CHECKING


if TYPE_CHECKING:
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
        _patch_chain_call,
        _patch_llm_call,
        _patch_tool_call,
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
        _clear_chain_call,
        _clear_llm_call,
        _clear_tool_call,
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


def _patch_chain_call():
    from langchain.chains.base import Chain

    if "Chain._call__" in patched_symbols:
        return

    patched_symbols["Chain._call__"] = Chain.__call__

    _wrap_call(Chain)


def _clear_chain_call():
    from langchain.chains.base import Chain

    if "Chain._call__" not in patched_symbols:
        return
    Chain.__init__ = patched_symbols["Chain._call__"]
    del patched_symbols["Chain._call__"]


def _patch_llm_call():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._call__" in patched_symbols:
        return

    patched_symbols["BaseLLM._call__"] = BaseLLM.__call__

    _wrap_call(BaseLLM)


def _clear_llm_call():
    from langchain.llms.base import BaseLLM

    if "BaseLLM._call__" not in patched_symbols:
        return
    BaseLLM.__init__ = patched_symbols["BaseLLM._call__"]
    del patched_symbols["BaseLLM._call__"]


def _patch_tool_call():
    from langchain.tools.base import BaseTool

    if "BaseTool._call__" in patched_symbols:
        return

    patched_symbols["BaseTool._call__"] = BaseTool.__call__

    _wrap_call(BaseTool)


def _clear_tool_call():
    from langchain.tools.base import BaseTool

    if "BaseTool._call__" not in patched_symbols:
        return
    BaseTool.__init__ = patched_symbols["BaseTool._call__"]
    del patched_symbols["BaseTool._call__"]


def _wrap_call(
    cls,
):
    from langchain.callbacks.manager import CallbackManager

    current_call = None
    if hasattr(cls, "__call__"):
        current_call = cls.__call__

    def call(self, *args, **kwargs):
        if current_call:
            inputs = self.prep_inputs(*args)
            callback_manager = CallbackManager.configure(
                inspect.signature(self.__call__).parameters.get("callbacks"),
                self.callbacks,
                self.verbose,
            )
            new_arg_supported = inspect.signature(self._call).parameters.get(
                "run_manager"
            )
            run_manager = callback_manager.on_chain_start(
                {
                    "name": self.__class__.__name__,
                    "_self": self,
                },
                inputs,
            )
            try:
                outputs = (
                    self._call(inputs, run_manager=run_manager)
                    if new_arg_supported
                    else self._call(inputs)
                )
            except (KeyboardInterrupt, Exception) as e:
                run_manager.on_chain_error(e)
                raise e
            run_manager.on_chain_end(outputs)
            return self.prep_outputs(
                inputs,
                outputs,
                inspect.signature(self.__call__).parameters.get("return_only_outputs"),
            )

    cls.__call__ = call
