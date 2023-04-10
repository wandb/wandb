__all__ = ("Sentry",)


import atexit
import functools
import os
import pathlib
import sys
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Type, Union
from urllib.parse import quote

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import sentry_sdk  # type: ignore
import sentry_sdk.utils  # type: ignore

import wandb
import wandb.env
import wandb.util

if TYPE_CHECKING:
    import wandb.sdk.internal.settings_static

SENTRY_DEFAULT_DSN = (
    "https://2592b1968ea94cca9b5ef5e348e094a7@o151352.ingest.sentry.io/4504800232407040"
)

SessionStatus = Literal["ok", "exited", "crashed", "abnormal"]


def _noop_if_disabled(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(self: Type["Sentry"], *args: Any, **kwargs: Any) -> Any:
        if self._disabled:
            return None
        return func(self, *args, **kwargs)

    return wrapper


class Sentry:
    _disabled: bool

    def __init__(self) -> None:
        self._disabled = not wandb.env.error_reporting_enabled()
        self._sent_messages: set = set()

        self.dsn = os.environ.get(wandb.env.SENTRY_DSN, SENTRY_DEFAULT_DSN)

        self.hub: Optional["sentry_sdk.hub.Hub"] = None

        # ensure we always end the Sentry session
        atexit.register(self.end_session)

    @property
    def environment(self) -> str:
        """Return the environment we're running in."""
        # check if we're in a git repo
        is_git = pathlib.Path(__file__).parent.parent.parent.joinpath(".git").exists()

        # these match the environments for gorilla
        return "development" if is_git else "production"

    @_noop_if_disabled
    def setup(self) -> None:
        """Setup Sentry SDK.

        We use lower-level APIs (i.e., not sentry_sdk.init) here
        to avoid the possibility of interfering with the user's
        own Sentry SDK setup.
        """
        client = sentry_sdk.Client(
            dsn=self.dsn,
            default_integrations=False,
            environment=self.environment,
            release=wandb.__version__,
        )
        self.hub = sentry_sdk.Hub(client)

    @_noop_if_disabled
    def message(self, message: str, repeat: bool = True) -> None:
        """Send a message to Sentry."""
        if not repeat and message in self._sent_messages:
            return
        self._sent_messages.add(message)
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
        handled: bool = False,
        status: Optional["SessionStatus"] = None,
    ) -> None:
        """Log an exception to Sentry."""
        error = Exception(exc) if isinstance(exc, str) else exc
        # based on self.hub.capture_exception(_exc)
        if error is not None:
            exc_info = sentry_sdk.utils.exc_info_from_error(error)
        else:
            exc_info = sys.exc_info()

        event, hint = sentry_sdk.utils.event_from_exception(
            exc_info,
            client_options=self.hub.client.options,  # type: ignore
            mechanism={"type": "generic", "handled": handled},
        )
        try:
            self.hub.capture_event(event, hint=hint)  # type: ignore
        except Exception:
            pass

        # if the status is not explicitly set, we'll set it to "crashed" if the exception
        # was unhandled, or "errored" if it was handled
        status = status or ("crashed" if not handled else "errored")  # type: ignore
        self.mark_session(status=status)

        client, _ = self.hub._stack[-1]
        client.flush()

        return None

    def reraise(self, exc: Any) -> None:
        """Re-raise an exception after logging it to Sentry.

        Use this for top-level exceptions when you want the user to see the traceback.

        Must be called from within an exception handler.
        """
        self.exception(exc)
        # this will messily add this "reraise" function to the stack trace,
        # but hopefully it's not too bad
        raise exc.with_traceback(sys.exc_info()[2])

    @_noop_if_disabled
    def start_session(self) -> None:
        """Start a new session."""
        assert self.hub is not None
        # get the current client and scope
        _, scope = self.hub._stack[-1]
        session = scope._session

        # if there's no session, start one
        if session is None:
            self.hub.start_session()

    @_noop_if_disabled
    def end_session(self) -> None:
        """End the current session."""
        assert self.hub is not None
        # get the current client and scope
        client, scope = self.hub._stack[-1]
        session = scope._session

        if session is not None and client is not None:
            self.hub.end_session()
            client.flush()

    @_noop_if_disabled
    def mark_session(self, status: Optional["SessionStatus"] = None) -> None:
        """Mark the current session with a status."""
        assert self.hub is not None
        _, scope = self.hub._stack[-1]
        session = scope._session

        if session is not None:
            session.update(status=status)

    @_noop_if_disabled
    def configure_scope(
        self,
        settings: Optional[
            Union[
                "wandb.sdk.wandb_settings.Settings",
                "wandb.sdk.internal.settings_static.SettingsStatic",
            ]
        ] = None,
        process_context: Optional[str] = None,
    ) -> None:
        """Configure the Sentry scope for the current thread.

        This function should be called at the beginning of every thread that
        will send events to Sentry. It sets the tags that will be applied to
        all events sent from this thread. It also tries to start a session
        if one doesn't already exist for this thread.
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
            "launch",
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
                val = getattr(settings, tag, None)
                if val not in (None, ""):
                    scope.set_tag(tag, val)

            # todo: update once #4982 is merged
            python_runtime = (
                "colab"
                if getattr(settings, "_colab", None)
                else ("jupyter" if getattr(settings, "_jupyter", None) else "python")
            )
            scope.set_tag("python_runtime", python_runtime)

            # Hack for constructing run_url and sweep_url given run_id and sweep_id
            required = ("entity", "project", "base_url")
            params = {key: getattr(settings, key, None) for key in required}
            if all(params.values()):
                # here we're guaranteed that entity, project, base_url all have valid values
                app_url = wandb.util.app_url(params["base_url"])  # type: ignore
                ent, proj = (quote(params[k]) for k in ("entity", "project"))  # type: ignore

                # TODO: the settings object will be updated to contain run_url and sweep_url
                # This is done by passing a settings_map in the run_start protocol buffer message
                for word in ("run", "sweep"):
                    _url, _id = f"{word}_url", f"{word}_id"
                    if not getattr(settings, _url, None) and getattr(
                        settings, _id, None
                    ):
                        scope.set_tag(
                            _url,
                            f"{app_url}/{ent}/{proj}/{word}s/{getattr(settings, _id, None)}",
                        )

            if hasattr(settings, "email"):
                scope.user = {"email": settings.email}  # noqa

        # todo: add back the option to pass general tags see: c645f625d1c1a3db4a6b0e2aa8e924fee101904c (wandb/util.py)

        self.start_session()
