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
import sys

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from packaging import version

import wandb
import wandb.util
from wandb.sdk.data_types import trace_tree
from wandb.sdk.lib import telemetry as wb_telemetry
from wandb.sdk.lib.paths import StrPath

langchain = wandb.util.get_module(
    name="langchain",
    required="To use the LangChain WandbTracer you need to have the `langchain` python "
    "package installed. Please install it with `pip install langchain`.",
)

if version.parse(langchain.__version__) < version.parse("0.0.170"):
    raise ValueError(
        "The Weights & Biases Langchain integration does not support versions 0.0.169 and lower. "
        "To ensure proper functionality, please use version 0.0.170 or higher."
    )

# We want these imports after the import_langchain() call, so that we can
# catch the ImportError if langchain is not installed.

# isort: off
from langchain.callbacks.tracers.base import BaseTracer  # noqa: E402, I001

from .util import (  # noqa: E402
    print_wandb_init_message,
    safely_convert_lc_run_to_wb_span,
    # safely_convert_model_to_dict,
    # safely_get_span_producing_model,
)

if TYPE_CHECKING:
    from langchain.callbacks.base import BaseCallbackHandler
    from langchain.callbacks.tracers.schemas import Run

    from wandb import Settings as WBSettings
    from wandb.wandb_run import Run as WBRun


class WandbRunArgs(TypedDict):
    job_type: Optional[str]
    dir: Optional[StrPath]
    config: Union[Dict, str, None]
    project: Optional[str]
    entity: Optional[str]
    reinit: Optional[bool]
    tags: Optional[Sequence]
    group: Optional[str]
    name: Optional[str]
    notes: Optional[str]
    magic: Optional[Union[dict, str, bool]]
    config_exclude_keys: Optional[List[str]]
    config_include_keys: Optional[List[str]]
    anonymous: Optional[str]
    mode: Optional[str]
    allow_val_change: Optional[bool]
    resume: Optional[Union[bool, str]]
    force: Optional[bool]
    tensorboard: Optional[bool]
    sync_tensorboard: Optional[bool]
    monitor_gym: Optional[bool]
    save_code: Optional[bool]
    id: Optional[str]
    settings: Union["WBSettings", Dict[str, Any], None]


class WandbTracer(BaseTracer):
    """Callback Handler that logs to Weights and Biases.

    This handler will log the model architecture and run traces to Weights and Biases. This will
    ensure that all LangChain activity is logged to W&B.
    """

    _run: Optional["WBRun"] = None
    _run_args: Optional[WandbRunArgs] = None

    @classmethod
    def init(
        cls,
        run_args: Optional[WandbRunArgs] = None,
        include_stdout: bool = True,
        additional_handlers: Optional[List["BaseCallbackHandler"]] = None,
    ) -> None:
        """Method provided for backwards compatibility. Please directly construct `WandbTracer` instead."""
        message = """Global autologging is not currently supported for the LangChain integration.
Please directly construct a `WandbTracer` and add it to the list of callbacks. For example:

LLMChain(llm, callbacks=[WandbTracer()])
# end of notebook / script:
WandbTracer.finish()"""
        wandb.termlog(message)

    def __init__(self, run_args: Optional[WandbRunArgs] = None, **kwargs: Any) -> None:
        """Initializes the WandbTracer.

        Parameters:
            run_args: (dict, optional) Arguments to pass to `wandb.init()`. If not provided, `wandb.init()` will be
                called with no arguments. Please refer to the `wandb.init` for more details.

        To use W&B to monitor all LangChain activity, add this tracer like any other langchain callback
        ```
        from wandb.integration.langchain import WandbTracer
        LLMChain(llm, callbacks=[WandbTracer()])
        # end of notebook / script:
        WandbTracer.finish()
        ```.
        """
        super().__init__(**kwargs)
        self._run_args = run_args
        self._ensure_run(should_print_url=(wandb.run is None))

    @staticmethod
    def finish() -> None:
        """Waits for all asynchronous processes to finish and data to upload.

        Proxy for `wandb.finish()`.
        """
        wandb.finish()

    def _log_trace_from_run(self, run: "Run") -> None:
        """Logs a LangChain Run to W*B as a W&B Trace."""
        self._ensure_run()

        root_span = safely_convert_lc_run_to_wb_span(run)
        if root_span is None:
            return

        model_dict = None

        # TODO: Uncomment this once we have a way to get the model from a run
        # model = safely_get_span_producing_model(run)
        # if model is not None:
        #     model_dict = safely_convert_model_to_dict(model)

        model_trace = trace_tree.WBTraceTree(
            root_span=root_span,
            model_dict=model_dict,
        )
        wandb.run.log({"langchain_trace": model_trace})

    def _ensure_run(self, should_print_url=False) -> None:
        """Ensures an active W&B run exists.

        If not, will start a new run with the provided run_args.
        """
        if wandb.run is None:
            # Make a shallow copy of the run args, so we don't modify the original
            run_args = self._run_args or {}  # type: ignore
            run_args: dict = {**run_args}  # type: ignore

            # Prefer to run in silent mode since W&B has a lot of output
            # which can be undesirable when dealing with text-based models.
            if "settings" not in run_args:  # type: ignore
                run_args["settings"] = {"silent": True}  # type: ignore

            # Start the run and add the stream table
            wandb.init(**run_args)

            if should_print_url:
                print_wandb_init_message(wandb.run.settings.run_url)

        with wb_telemetry.context(wandb.run) as tel:
            tel.feature.langchain_tracer = True

    # Start of required methods (these methods are required by the BaseCallbackHandler interface)
    @property
    def always_verbose(self) -> bool:
        """Whether to call verbose callbacks even if verbose is False."""
        return True

    def _generate_id(self) -> Optional[Union[int, str]]:
        """Generate an id for a run."""
        return None

    def _persist_run(self, run: "Run") -> None:
        """Persist a run."""
        try:
            self._log_trace_from_run(run)
        except Exception:
            # Silently ignore errors to not break user code
            pass

    # End of required methods
