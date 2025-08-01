"""This module contains an integration with the LangChain library.

Specifically, it exposes a `WandbTracer` class that can be used to stream
LangChain activity to W&B. The intended usage pattern is to call
`tracer = WandbTracer()` at the top of the script/notebook, and call
`tracer.finish()` at the end of the script/notebook.
 This will stream all LangChain activity to W&B.

Technical Note:
LangChain is in very rapid development - meaning their APIs and schemas are actively changing.
As a matter of precaution, any call to LangChain apis, or use of their returned data is wrapped
in a try/except block. This is to ensure that if a breaking change is introduced, the W&B
integration will not break user code. The one exception to the rule is at import time. If
LangChain is not installed, or the symbols are not in the same place, the appropriate error
will be raised when importing this module.
"""

from packaging import version

import wandb.util
from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk.lib import deprecate

langchain = wandb.util.get_module(
    name="langchain",
    required="To use the LangChain WandbTracer you need to have the `langchain` python "
    "package installed. Please install it with `pip install langchain`.",
)

if version.parse(langchain.__version__) < version.parse("0.0.188"):
    raise ValueError(
        "The Weights & Biases Langchain integration does not support versions 0.0.187 and lower. "
        "To ensure proper functionality, please use version 0.0.188 or higher."
    )

# isort: off
from langchain.callbacks.tracers import WandbTracer  # noqa: E402


class WandbTracer(WandbTracer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deprecate.deprecate(
            field_name=Deprecated.langchain_tracer,
            warning_message="This feature is deprecated and has been moved to `langchain`. Enable tracing by setting "
            "LANGCHAIN_WANDB_TRACING=true in your environment. See the documentation at "
            "https://python.langchain.com/docs/ecosystem/integrations/agent_with_wandb_tracing for guidance. "
            "Replace your current import with `from langchain.callbacks.tracers import WandbTracer`.",
        )
