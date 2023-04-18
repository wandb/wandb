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


class PatchOpenAIAPI:
    symbols: List[Literal["Edit", "Completion", "ChatCompletion"]] = [
        "Edit",
        "Completion",
        "ChatCompletion",
    ]

    def __init__(self):
        self.original_methods: Dict[str, Any] = {}
        self.resolver = OpenAIRequestResponseResolver()
        self._openai = None

    @property
    def openai(self):
        if self._openai is None:
            self._openai = wandb.util.get_module(
                name="openai",
                required="To use the W&B OpenAI Autolog, you need to have the `openai` python "
                "package installed. Please install it with `pip install openai`.",
                lazy=False,
            )
        return self._openai

    def patch(self, run: "wandb.sdk.wandb_run.Run"):
        for symbol in self.symbols:
            original = getattr(self.openai, symbol).create

            def method_factory(original_method: Any):
                def create(*args, **kwargs):
                    with Timer() as timer:
                        result = original_method(*args, **kwargs)
                    trace = self.resolver(kwargs, result, timer.elapsed)
                    if trace is not None:
                        run.log({"trace": trace})
                    return result

                return create

            # save original method
            self.original_methods[symbol] = original
            # monkeypatch
            getattr(self.openai, symbol).create = method_factory(original)

    def unpatch(self):
        for symbol, original in self.original_methods.items():
            getattr(self.openai, symbol).create = original


class AutologOpenAI:
    def __init__(self):
        self.patch_openai_api = PatchOpenAIAPI()
        self.run: Optional["wandb.sdk.wandb_run.Run"] = None

    def enable(self, project: str):
        self.run = wandb.init(project=project)
        self.patch_openai_api.patch(self.run)

    def disable(self):
        self.run.finish()
        self.patch_openai_api.unpatch()
