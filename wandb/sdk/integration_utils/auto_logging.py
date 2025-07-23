import asyncio
import functools
import inspect
import logging
from typing import Any, Dict, Optional, Protocol, Sequence, TypeVar

import wandb.sdk
import wandb.util
from wandb.sdk.lib import telemetry as wb_telemetry
from wandb.sdk.lib.timer import Timer

logger = logging.getLogger(__name__)


AutologInitArgs = Optional[Dict[str, Any]]


K = TypeVar("K", bound=str)
V = TypeVar("V")


class Response(Protocol[K, V]):
    def __getitem__(self, key: K) -> V: ...  # pragma: no cover

    def get(
        self, key: K, default: Optional[V] = None
    ) -> Optional[V]: ...  # pragma: no cover


class ArgumentResponseResolver(Protocol):
    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Optional[Dict[str, Any]]: ...  # pragma: no cover


class PatchAPI:
    def __init__(
        self,
        name: str,
        symbols: Sequence[str],
        resolver: ArgumentResponseResolver,
    ) -> None:
        """Patches the API to log wandb Media or metrics."""
        # name of the LLM provider, e.g. "Cohere" or "OpenAI" or package name like "Transformers"
        self.name = name
        # api library name, e.g. "cohere" or "openai" or "transformers"
        self._api = None
        # dictionary of original methods
        self.original_methods: Dict[str, Any] = {}
        # list of symbols to patch, e.g. ["Client.generate", "Edit.create"] or ["Pipeline.__call__"]
        self.symbols = symbols
        # resolver callable to convert args/response into a dictionary of wandb media objects or metrics
        self.resolver = resolver

    @property
    def set_api(self) -> Any:
        """Returns the API module."""
        lib_name = self.name.lower()
        if self._api is None:
            self._api = wandb.util.get_module(
                name=lib_name,
                required=f"To use the W&B {self.name} Autolog, "
                f"you need to have the `{lib_name}` python "
                f"package installed. Please install it with `pip install {lib_name}`.",
                lazy=False,
            )
        return self._api

    def patch(self, run: "wandb.Run") -> None:
        """Patches the API to log media or metrics to W&B."""
        for symbol in self.symbols:
            # split on dots, e.g. "Client.generate" -> ["Client", "generate"]
            symbol_parts = symbol.split(".")
            # and get the attribute from the module
            original = functools.reduce(getattr, symbol_parts, self.set_api)

            def method_factory(original_method: Any):
                async def async_method(*args, **kwargs):
                    future = asyncio.Future()

                    async def callback(coro):
                        try:
                            result = await coro
                            loggable_dict = self.resolver(
                                args, kwargs, result, timer.start_time, timer.elapsed
                            )
                            if loggable_dict is not None:
                                run.log(loggable_dict)
                            future.set_result(result)
                        except Exception as e:
                            logger.warning(e)

                    with Timer() as timer:
                        coro = original_method(*args, **kwargs)
                        asyncio.ensure_future(callback(coro))

                    return await future

                def sync_method(*args, **kwargs):
                    with Timer() as timer:
                        result = original_method(*args, **kwargs)
                        try:
                            loggable_dict = self.resolver(
                                args, kwargs, result, timer.start_time, timer.elapsed
                            )
                            if loggable_dict is not None:
                                run.log(loggable_dict)
                        except Exception as e:
                            logger.warning(e)
                        return result

                if inspect.iscoroutinefunction(original_method):
                    return functools.wraps(original_method)(async_method)
                else:
                    return functools.wraps(original_method)(sync_method)

            # save original method
            self.original_methods[symbol] = original
            # monkey patch the method
            if len(symbol_parts) == 1:
                setattr(self.set_api, symbol_parts[0], method_factory(original))
            else:
                setattr(
                    functools.reduce(getattr, symbol_parts[:-1], self.set_api),
                    symbol_parts[-1],
                    method_factory(original),
                )

    def unpatch(self) -> None:
        """Unpatches the API."""
        for symbol, original in self.original_methods.items():
            # split on dots, e.g. "Client.generate" -> ["Client", "generate"]
            symbol_parts = symbol.split(".")
            # unpatch the method
            if len(symbol_parts) == 1:
                setattr(self.set_api, symbol_parts[0], original)
            else:
                setattr(
                    functools.reduce(getattr, symbol_parts[:-1], self.set_api),
                    symbol_parts[-1],
                    original,
                )


class AutologAPI:
    def __init__(
        self,
        name: str,
        symbols: Sequence[str],
        resolver: ArgumentResponseResolver,
        telemetry_feature: Optional[str] = None,
    ) -> None:
        """Autolog API calls to W&B."""
        self._telemetry_feature = telemetry_feature
        self._patch_api = PatchAPI(
            name=name,
            symbols=symbols,
            resolver=resolver,
        )
        self._name = self._patch_api.name
        self._run: Optional[wandb.Run] = None
        self.__run_created_by_autolog: bool = False

    @property
    def _is_enabled(self) -> bool:
        """Returns whether autologging is enabled."""
        return self._run is not None

    def __call__(self, init: AutologInitArgs = None) -> None:
        """Enable autologging."""
        self.enable(init=init)

    def _run_init(self, init: AutologInitArgs = None) -> None:
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

    def enable(self, init: AutologInitArgs = None) -> None:
        """Enable autologging.

        Args:
            init: Optional dictionary of arguments to pass to wandb.init().

        """
        if self._is_enabled:
            logger.info(
                f"{self._name} autologging is already enabled, disabling and re-enabling."
            )
            self.disable()

        logger.info(f"Enabling {self._name} autologging.")
        self._run_init(init=init)

        self._patch_api.patch(self._run)

        if self._telemetry_feature:
            with wb_telemetry.context(self._run) as tel:
                setattr(tel.feature, self._telemetry_feature, True)

    def disable(self) -> None:
        """Disable autologging."""
        if self._run is None:
            return

        logger.info(f"Disabling {self._name} autologging.")

        if self.__run_created_by_autolog:
            self._run.finish()
            self.__run_created_by_autolog = False

        self._run = None

        self._patch_api.unpatch()
