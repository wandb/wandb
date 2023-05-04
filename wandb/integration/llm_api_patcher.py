import functools
import logging
import sys
from typing import Any, Dict, List, Optional, Sequence, TypeVar

import wandb.sdk
import wandb.util
from wandb.sdk.data_types import trace_tree
from wandb.sdk.lib import telemetry as wb_telemetry
from wandb.sdk.lib.timer import Timer


if sys.version_info >= (3, 8):
    from typing import Literal, Protocol
else:
    from typing_extensions import Literal, Protocol


logger = logging.getLogger(__name__)


AutologInitArgs = Optional[Dict[str, Any]]


K = TypeVar("K", bound=str)
V = TypeVar("V")


class Response(Protocol[K, V]):
    def __getitem__(self, key: K) -> V:
        ...  # pragma: no cover

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        ...  # pragma: no cover


class RequestResponseResolver(Protocol):
    def __call__(
        self,
        request: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Optional[trace_tree.WBTraceTree]:
        ...  # pragma: no cover


class PatchLLMAPI:
    def __init__(
        self,
        name: str,
        symbols: Sequence[str],
        resolver: RequestResponseResolver,
    ) -> None:
        """Patches the Cohere API to log traces to W&B."""
        self.name = name
        self._llm_api = None
        self.original_methods: Dict[str, Any] = {}
        self.symbols = symbols
        self.resolver = resolver

    @property
    def llm_api(self) -> Any:
        """Returns the cohere module."""
        lib_name = self.name.lower()
        if self._llm_api is None:
            self._llm_api = wandb.util.get_module(
                name=lib_name,
                required=f"To use the W&B {self.name} Autolog, "
                f"you need to have the `{lib_name}` python "
                f"package installed. Please install it with `pip install {lib_name}`.",
                lazy=False,
            )
        return self._llm_api

    def patch(self, run: "wandb.sdk.wandb_run.Run") -> None:
        """Patches the LLM API to log traces to W&B."""
        for symbol in self.symbols:
            original = getattr(self.cohere.Client, symbol)

            def method_factory(original_method: Any):
                @functools.wraps(original_method)
                def method(*args, **kwargs):
                    with Timer() as timer:
                        result = original_method(*args, **kwargs)
                    try:
                        trace = self.resolver(
                            kwargs, result, timer.start_time, timer.elapsed
                        )
                        if trace is not None:
                            run.log({"trace": trace})
                    except Exception:
                        # logger.warning(e)
                        pass
                    return result

                return method

            # save original method
            self.original_methods[symbol] = original
            # monkeypatch
            setattr(self.cohere.Client, symbol, method_factory(original))

    def unpatch(self) -> None:
        """Unpatches the Cohere API."""
        for symbol, original in self.original_methods.items():
            setattr(self.cohere.Client, symbol, original)


class AutologCohere:
    def __init__(self) -> None:
        """Autolog Cohere API calls to W&B."""
        self._patch_cohere_api = PatchCohereAPI()
        self._run: Optional["wandb.sdk.wandb_run.Run"] = None
        self.__run_created_by_autolog: bool = False

    @property
    def _is_enabled(self) -> bool:
        """Returns whether autologging is enabled."""
        return self._run is not None

    def __call__(self, init: AutologCohereInitArgs = None) -> None:
        """Enable Cohere autologging."""
        self.enable(init=init)

    def _run_init(self, init: AutologCohereInitArgs = None) -> None:
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

    def enable(self, init: AutologCohereInitArgs = None) -> None:
        """Enable Cohere autologging.

        Args:
            init: Optional dictionary of arguments to pass to wandb.init().

        """
        if self._is_enabled:
            logger.info(
                "Cohere autologging is already enabled, disabling and re-enabling."
            )
            self.disable()

        logger.info("Enabling Cohere autologging.")
        self._run_init(init=init)

        self._patch_cohere_api.patch(self._run)

        with wb_telemetry.context(self._run) as tel:
            tel.feature.cohere_autolog = True

    def disable(self) -> None:
        """Disable Cohere autologging."""
        if self._run is None:
            return

        logger.info("Disabling Cohere autologging.")

        if self.__run_created_by_autolog:
            self._run.finish()
            self.__run_created_by_autolog = False

        self._run = None

        self._patch_cohere_api.unpatch()
