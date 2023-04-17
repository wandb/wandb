"""This module contains an integration with the LangChain library.

Specifically, it exposes
a `WandbTracer` class that can be used to stream LangChain activity to W&B. The intended
usage pattern is to call `WandbTracer.init()` at the top of the script/notebook, and call
`WandbTracer.finish()` at the end of the script/notebook. This will automatically stream
all LangChain activity to W&B.

Technical Note:
LangChain is in very rapid development - meaning their APIs and schemas are actively changing.
As a matter of precaution, any call to langchain apis, or use of their returned data is wrapped
in a try/except block. This is to ensure that if a breaking change is introduced, the wandb
integration will not break user code. The one exception to the rule is at import time. If
langchain is not installed, or the symbols are not in the same place, the appropriate error
will be raised when importing this module.
"""


import json
import pathlib
from typing import TYPE_CHECKING, TypedDict  # type: ignore

import wandb
from wandb.sdk.data_types import trace_tree

from . import import_check, monkeypatch
from .util import (
    print_wandb_init_message,
    safely_convert_lc_run_to_wb_span,
    safely_convert_model_to_dict,
    safely_get_span_producing_model,
)

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Sequence, Union, cast

    from langchain.callbacks.base import BaseCallbackHandler
    from langchain.callbacks.tracers.schemas import BaseRun, TracerSessionCreate

    from wandb import Settings as WBSettings
    from wandb.wandb_run import Run as WBRun

# We want these imports after the import_langchain() call, so that we can
# catch the ImportError if langchain is not installed.
from langchain.callbacks import StdOutCallbackHandler, get_callback_manager
from langchain.callbacks.tracers.base import SharedTracer
from langchain.callbacks.tracers.schemas import ChainRun, LLMRun, ToolRun, TracerSession


class WandbRunArgs(TypedDict):
    job_type: Optional[str]
    dir: Union[str, pathlib.Path, None]
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


class WandbTracer(SharedTracer):
    """Callback Handler that logs to Weights and Biases.

    Parameters:
        run_args (dict): The arguments to pass to wandb.init().

    This handler will log the model architecture and run traces to Weights and Biases.
    """

    _run: Optional["WBRun"] = None
    _run_args: Optional[WandbRunArgs] = None

    @classmethod
    def init(
        cls,
        run_args: Optional[WandbRunArgs] = None,
        include_stdout: bool = True,
        additional_handlers: Optional[list["BaseCallbackHandler"]] = None,
    ) -> None:
        """Sets up a WandbTracer and makes it the default handler.

        To use W&B to
        monitor all LangChain activity, simply call this function at the top of
        the notebook or script:
        ```
        from wandb.integration.langchain import WandbTracer
        WandbTracer.watch_all()
        # ...
        # end of notebook / script:
        WandbTracer.stop_watch()
        ```.

        It is safe to call this repeatedly with the same arguments (such as in a
        notebook), as it will only create a new run if the run_args differ.
        """
        tracer = cls()
        tracer.init_run(run_args)
        tracer.load_session("")
        manager = get_callback_manager()
        handlers: list["BaseCallbackHandler"] = [tracer]
        if include_stdout:
            handlers.append(StdOutCallbackHandler())
        additional_handlers = additional_handlers or []
        manager.set_handlers(handlers + additional_handlers)

    @staticmethod
    def finish() -> None:
        """Stops watching all LangChain activity and resets the default handler."""
        if WandbTracer._instance:
            cast(WandbTracer, WandbTracer._instance).finish_run()
            manager = get_callback_manager()
            manager.set_handlers([])

    def init_run(self, run_args: Optional[WandbRunArgs] = None) -> None:
        """Initialize wandb if it has not been initialized.

        We only want to start a new run if the run args differ. This will reduce
        the number of W&B runs created, which is more ideal in a notebook
        setting.
        """
        monkeypatch.ensure_patched()
        if (
            wandb.run is not None
            and self._run is not None
            and json.dumps(self._run_args, sort_keys=True)
            == json.dumps(run_args, sort_keys=True)
        ):
            print_wandb_init_message(self._run.settings.run_url)
            return
        self._run_args = run_args
        self._run = None

        # Make a shallow copy of the run args so we don't modify the original
        run_args = run_args or {}  # type: ignore
        run_args: dict = {**run_args}  # type: ignore

        # Prefer to run in silent mode since W&B has a lot of output
        # which can be undesirable when dealing with text-based models.
        if "settings" not in run_args:  # type: ignore
            run_args["settings"] = {"silent": True}  # type: ignore

        # Start the run and add the stream table
        self._run = wandb.init(**run_args)
        print_wandb_init_message(self._run.settings.run_url)

    def finish_run(self) -> None:
        """Waits for W&B data to upload.

        It is recommended to call this function before terminating the kernel or
        python script.
        """
        if self._run is not None:
            url = self._run.settings.run_url
            self._run.finish()
            wandb.termlog(f"Finished uploading data to W&B at {url}")
        else:
            print("W&B run not started. Skipping.")
        monkeypatch.clear_patches()

    def _log_trace_from_run(self, run: "BaseRun") -> None:
        if self._run is None:
            return

        root_span = safely_convert_lc_run_to_wb_span(run)
        if root_span is None:
            return

        model_dict = None
        model = safely_get_span_producing_model(run)
        if model is not None:
            model_dict = safely_convert_model_to_dict(model)

        model_trace = trace_tree.WBTraceTree(
            root_span=root_span,
            model_dict=model_dict,
        )
        self._run.log({"langchain_trace": model_trace})

    # Start of required methods
    @property
    def always_verbose(self) -> bool:
        """Whether to call verbose callbacks even if verbose is False."""
        return True

    def _generate_id(self) -> Optional[Union[int, str]]:
        """Generate an id for a run."""
        return None

    def _persist_run(self, run: "BaseRun") -> None:
        """Persist a run."""
        try:
            self._log_trace_from_run(run)
        except Exception:
            # Silently ignore errors to not break user code
            pass

    def _persist_session(
        self, session_create: "TracerSessionCreate"
    ) -> "TracerSession":
        """Persist a session."""
        try:
            return TracerSession(id=1, **session_create.dict())
        except Exception:
            return TracerSession(id=1)

    def load_session(self, session_name: str) -> "TracerSession":
        """Load a session from the tracer."""
        self._session = TracerSession(id=1)
        return self._session

    def load_default_session(self) -> "TracerSession":
        """Load the default tracing session and set it as the Tracer's session."""
        self._session = TracerSession(id=1)
        return self._session

    def _add_child_run(
        self,
        parent_run: Union["ChainRun", "ToolRun"],
        child_run: Union["LLMRun", "ChainRun", "ToolRun"],
    ) -> None:
        """Add child run to a chain run or tool run."""
        try:
            parent_run.child_runs.append(child_run)
        except Exception:
            # Silently ignore errors to not break user code
            pass

    # End of required methods
