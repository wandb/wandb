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


import json
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

if version.parse(langchain.__version__) < version.parse("0.0.154"):
    raise ValueError(
        "The Weights & Biases Langchain integration is incompatible with versions 0.0.154 and below. "
        "Please use a version above 0.0.154 to ensure proper functionality."
    )

# We want these imports after the import_langchain() call, so that we can
# catch the ImportError if langchain is not installed.

from langchain.callbacks.tracers.base import BaseTracer  # noqa: E402
from langchain.callbacks.tracers.schemas import TracerSession  # noqa: E402

from . import monkeypatch  # noqa: E402
from .util import (  # noqa: E402
    print_wandb_init_message,
    safely_convert_lc_run_to_wb_span,
    safely_convert_model_to_dict,
    safely_get_span_producing_model,
)

if TYPE_CHECKING:
    from langchain.callbacks.tracers.schemas import BaseRun, TracerSessionCreate

    from wandb import Settings as WBSettings
    from wandb.wandb_run import Run as WBRun

monkeypatch.ensure_patched()


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

    def __init__(self, run_args: Optional[WandbRunArgs] = None, **kwargs: Any) -> None:
        """Initializes the WandbTracer.
        Parameters:
            run_args: (dict, optional) Arguments to pass to `wandb.init()`. If not provided, `wandb.init()` will be
                called with no arguments. Please refer to the `wandb.init` for more details.

        To use W&B to monitor all LangChain activity, add this tracer like any other langchain callback
        ```
        from wandb.integration.langchain import WandbTracer
        tracer = WandbTracer()
        # ...
        LLMChain(llm, callbacks=[tracer])
        # end of notebook / script:
        tracer.finish()
        ```.
        """
        super().__init__(**kwargs)
        self._run_args = run_args
        self.init_run(run_args)
        self.session = self.load_session("")

    def init_run(self, run_args: Optional[WandbRunArgs] = None) -> None:
        """Initialize wandb if it has not been initialized.

        Parameters:
            run_args: (dict, optional) Arguments to pass to `wandb.init()`. If not provided, `wandb.init()` will be
                called with no arguments. Please refer to the `wandb.init` for more details.

        We only want to start a new run if the run args differ. This will reduce
        the number of W&B runs created, which is more ideal in a notebook
        setting. Note: it is uncommon to call this method directly. Instead, you
        should use the `WandbTracer.init()` method. This method is exposed if you
        want to manually initialize the tracer and add it to the list of handlers.
        """
        # Add a check for differences between wandb.run and self._run
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

        # Make a shallow copy of the run args, so we don't modify the original
        run_args = run_args or {}  # type: ignore
        run_args: dict = {**run_args}  # type: ignore

        # Prefer to run in silent mode since W&B has a lot of output
        # which can be undesirable when dealing with text-based models.
        if "settings" not in run_args:  # type: ignore
            run_args["settings"] = {"silent": True}  # type: ignore

        # Start the run and add the stream table
        self._run = wandb.init(**run_args)
        print_wandb_init_message(self._run.settings.run_url)

        with wb_telemetry.context(self._run) as tel:
            tel.feature.langchain_tracer = True

    def finish(self) -> None:
        """Stops watching all LangChain activity and Waits for W&B data to upload.
        It is recommended to call this function before terminating the kernel or python script.
        """
        if self._run is not None:
            url = self._run.settings.run_url
            self._run.finish()
            self._run = None
            self._run_args = None
            wandb.termlog(f"Finished uploading data to W&B at {url}")
        else:
            wandb.termlog("W&B run not started. Skipping.")

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

    # Start of required methods (these methods are required by the BaseCallbackHandler interface)
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

    # End of required methods


def autolog(run_args: Optional[WandbRunArgs] = None):
    monkeypatch.clear_patches()
    tracer = WandbTracer(run_args=run_args)
    monkeypatch.ensure_patched(tracer=tracer)


def disable_autolog():
    monkeypatch.clear_patches()
