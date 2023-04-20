import functools
import logging
import sys
from typing import Any, Dict, List, Optional

import wandb.sdk
import wandb.util
from wandb.sdk.lib import telemetry as wb_telemetry
from wandb.sdk.lib.timer import Timer

from .resolver import OpenAIRequestResponseResolver

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


logger = logging.getLogger(__name__)


AutologOpenAIInitArgs = Optional[Dict[str, Any]]


class PatchOpenAIAPI:
    symbols: List[Literal["Edit", "Completion", "ChatCompletion"]] = [
        "Edit",
        "Completion",
        "ChatCompletion",
    ]

    def __init__(self) -> None:
        """Patches the OpenAI API to log traces to W&B."""
        self.original_methods: Dict[str, Any] = {}
        self.resolver = OpenAIRequestResponseResolver()
        self._openai = None

    @property
    def openai(self) -> Any:
        """Returns the openai module."""
        if self._openai is None:
            self._openai = wandb.util.get_module(
                name="openai",
                required="To use the W&B OpenAI Autolog, you need to have the `openai` python "
                "package installed. Please install it with `pip install openai`.",
                lazy=False,
            )
        return self._openai

    def patch(self, run: "wandb.sdk.wandb_run.Run") -> None:
        """Patches the OpenAI API to log traces to W&B."""
        for symbol in self.symbols:
            original = getattr(self.openai, symbol).create

            def method_factory(original_method: Any):
                @functools.wraps(original_method)
                def create(*args, **kwargs):
                    with Timer() as timer:
                        result = original_method(*args, **kwargs)
                    try:
                        trace = self.resolver(kwargs, result, timer.elapsed)
                        if trace is not None:
                            run.log({"trace": trace})
                    except Exception:
                        # logger.warning(e)
                        pass
                    return result

                return create

            # save original method
            self.original_methods[symbol] = original
            # monkeypatch
            getattr(self.openai, symbol).create = method_factory(original)

    def unpatch(self) -> None:
        """Unpatches the OpenAI API."""
        for symbol, original in self.original_methods.items():
            getattr(self.openai, symbol).create = original


class AutologOpenAI:
    def __init__(self) -> None:
        """Autolog OpenAI API calls to W&B."""
        self._patch_openai_api = PatchOpenAIAPI()
        self._run: Optional["wandb.sdk.wandb_run.Run"] = None
        self.__run_created_by_autolog: bool = False

    @property
    def _is_enabled(self) -> bool:
        """Returns whether autologging is enabled."""
        return self._run is not None

    def __call__(self, init: AutologOpenAIInitArgs = None) -> None:
        """Enable OpenAI autologging."""
        self.enable(init=init)

    def _run_init(self, init: AutologOpenAIInitArgs = None) -> None:
        """Handle wandb run initialization."""
        # - autolog(init: dict = {...}) calls wandb.init(**{...})
        #   regardless of whether there is a wandb.run or not,
        #   we only track if the run was created by autolog
        #    - todo: autolog(init: dict | run = run) would use the user-provided run
        # - autolog() uses the wandb.run if there is one, otherwise it calls wandb.init()
        if init:
            _wandb_run = wandb.run
            # we delegate dealing with the init dict to wandb.init()
            self._run = wandb.init(**init)
            if _wandb_run != self._run:
                self.__run_created_by_autolog = True
        elif wandb.run is None:
            self._run = wandb.init()
            self.__run_created_by_autolog = True
        else:
            self._run = wandb.run

    def enable(self, init: AutologOpenAIInitArgs = None) -> None:
        """Enable OpenAI autologging.

        Args:
            init: Optional dictionary of arguments to pass to wandb.init().

        """
        if self._is_enabled:
            logger.info(
                "OpenAI autologging is already enabled, disabling and re-enabling."
            )
            self.disable()

        logger.info("Enabling OpenAI autologging.")
        self._run_init(init=init)

        self._patch_openai_api.patch(self._run)

        with wb_telemetry.context(self._run) as tel:
            tel.feature.openai_autolog = True

    def disable(self) -> None:
        """Disable OpenAI autologging."""
        if self._run is None:
            return

        logger.info("Disabling OpenAI autologging.")

        if self.__run_created_by_autolog:
            self._run.finish()
            self.__run_created_by_autolog = False

        self._run = None

        self._patch_openai_api.unpatch()
