import logging
import sys
from typing import Any, Dict, List, Optional

import wandb.sdk
import wandb.util
from wandb.sdk.lib.timer import Timer

from .resolver import OpenAIRequestResponseResolver

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


logger = logging.getLogger(__name__)


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
        self.patch_openai_api = PatchOpenAIAPI()
        self.run: Optional["wandb.sdk.wandb_run.Run"] = None
        self.__user_provided_run: bool = False

    def __call__(self, run: Optional["wandb.sdk.wandb_run.Run"] = None) -> None:
        """Enable OpenAI autologging."""
        self.enable(run=run)

    def enable(self, run: Optional["wandb.sdk.wandb_run.Run"] = None) -> None:
        """Enable OpenAI autologging.

        Args:
            run: Optional wandb run object. If not specified, wandb.init() will be called.

        """
        if self.run is not None:
            wandb.termwarn(
                "OpenAI autologging is already enabled. Skipping.", repeat=False
            )
            return
        if run is None:
            logger.info("Enabling OpenAI autologging (no run specified).")
            self.run = wandb.init()
        else:
            logger.info("Enabling OpenAI autologging.")
            self.__user_provided_run = True
            self.run = run

        self.patch()

    def disable(self) -> None:
        """Disable OpenAI autologging."""
        if self.run is not None and not self.__user_provided_run:
            self.run.finish()
        self.run = None
        self.__user_provided_run = False
        self.unpatch()

    def patch(self) -> None:
        """Patch OpenAI API for autologging."""
        self.patch_openai_api.patch(self.run)

    def unpatch(self) -> None:
        """Unpatch OpenAI API."""
        self.patch_openai_api.unpatch()
