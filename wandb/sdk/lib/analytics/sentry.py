__all__ = ("Sentry",)


import functools
import os
import sys
import time
from types import TracebackType
from typing import Any, Callable, Optional, Tuple, Type, Union
from urllib.parse import quote

import sentry_sdk  # type: ignore

import wandb
import wandb.env
import wandb.sdk.internal
import wandb.sdk.internal.settings_static
import wandb.util

# SENTRY_DEFAULT_DSN = (
#     "https://a2f1d701163c42b097b9588e56b1c37e@o151352.ingest.sentry.io/5288891"
# )
# project junk:
SENTRY_DEFAULT_DSN = (
    "https://45bbbb93aacd42cf90785517b66e925b@o151352.ingest.sentry.io/6438430"
)


def _noop_if_disabled(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Type["Sentry"], *args: Any, **kwargs: Any) -> Any:
        if self._disabled:
            return None
        return func(self, *args, **kwargs)

    return wrapper


class Sentry:
    _disabled: bool

    def __init__(self, disabled: bool = False) -> None:
        self._disabled = disabled

        self.dsn = os.environ.get(wandb.env.SENTRY_DSN, SENTRY_DEFAULT_DSN)

        self.client: Optional["sentry_sdk.client.Client"] = None
        self.hub: Optional["sentry_sdk.hub.Hub"] = None

    @property
    def environment(self) -> str:
        # check if we're in a git repo
        is_git = os.path.exists(
            os.path.join(os.path.dirname(__file__), "../../../../..", ".git")
        )
        # these match the environments for gorilla
        return "development" if is_git else "production"

    @_noop_if_disabled
    def setup(self) -> None:
        self.client = sentry_sdk.Client(
            dsn=self.dsn,
            default_integrations=False,
            environment=self.environment,
            release=wandb.__version__,
        )
        self.hub = sentry_sdk.Hub(self.client)

    @_noop_if_disabled
    def message(self, message: str) -> None:
        self.hub.capture_message(message)  # type: ignore

    @_noop_if_disabled
    def exception(
        self,
        exc: Union[
            str,
            BaseException,
            Tuple[
                Optional[Type[BaseException]],
                Optional[BaseException],
                Optional[TracebackType],
            ],
            None,
        ],
        delay: bool = False,
    ) -> None:
        if isinstance(exc, str):
            self.hub.capture_exception(Exception(exc))  # type: ignore
        else:
            self.hub.capture_exception(exc)  # type: ignore
        if delay:
            time.sleep(2)
        return None

    def reraise(self, exc: Any, delay: bool = False) -> None:
        """Re-raise an exception after logging it to Sentry.

        Use this for top-level exceptions when you want the user to see the traceback.

        Must be called from within an exception handler.
        """
        self.exception(exc, delay=delay)
        # this will messily add this "reraise" function to the stack trace,
        # but hopefully it's not too bad
        raise exc.with_traceback(sys.exc_info()[2])

    @_noop_if_disabled
    def start_session(self) -> None:
        """Track session to get metrics about error-free rate."""
        assert self.hub is not None
        _, scope = self.hub._stack[-1]
        session = scope._session

        if session is None:
            # wandb.termlog("IMMA START A SESSION")
            # import threading
            # wandb.termlog(f"{threading.main_thread().name}  {threading.current_thread().name}")
            self.hub.start_session()

    @_noop_if_disabled
    def set_scope(
        self,
        settings: Optional[
            Union[
                "wandb.sdk.wandb_settings.Settings",
                "wandb.sdk.internal.settings_static.SettingsStatic",
            ]
        ] = None,
        process_context: Optional[str] = None,
    ) -> None:
        """Set the Sentry scope for the current thread.

        This function should be called at the beginning of every thread that
        will send events to Sentry. It sets the tags that will be applied to
        all events sent from this thread.
        """
        assert self.hub is not None
        settings_tags = (
            "entity",
            "project",
            "run_id",
            "run_url",
            "sweep_url",
            "sweep_id",
            "deployment",
            "_disable_service",
        )

        with self.hub.configure_scope() as scope:
            scope.set_tag("platform", wandb.util.get_platform_name())

            # set context
            if process_context:
                scope.set_tag("process_context", process_context)

            # apply settings tags
            if settings is None:
                return None

            for tag in settings_tags:
                val = settings[tag]
                if val not in (None, ""):
                    scope.set_tag(tag, val)

            # todo: update once #4982 is merged
            python_runtime = (
                "colab"
                if settings["_colab"]
                else ("jupyter" if settings["_jupyter"] else "python")
            )
            scope.set_tag("python_runtime", python_runtime)

            # Hack for constructing run_url and sweep_url given run_id and sweep_id
            required = ("entity", "project", "base_url")
            params = {key: settings[key] for key in required}
            if all(params.values()):
                # here we're guaranteed that entity, project, base_url all have valid values
                app_url = wandb.util.app_url(params["base_url"])
                ent, proj = (quote(params[k]) for k in ("entity", "project"))

                # TODO: the settings object will be updated to contain run_url and sweep_url
                # This is done by passing a settings_map in the run_start protocol buffer message
                for word in ("run", "sweep"):
                    _url, _id = f"{word}_url", f"{word}_id"
                    if not settings[_url] and settings[_id]:
                        scope.set_tag(
                            _url, f"{app_url}/{ent}/{proj}/{word}s/{settings[_id]}"
                        )

            if hasattr(settings, "email"):
                scope.user = {"email": settings.email}  # noqa

        self.start_session()
