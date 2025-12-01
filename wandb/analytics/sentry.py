from __future__ import annotations

import atexit
import contextlib
import functools
import os
import pathlib
import sys
import threading
from types import TracebackType
from typing import Any, Callable, Literal, TypeVar
from urllib.parse import quote

from typing_extensions import Concatenate, Never, ParamSpec

_P = ParamSpec("_P")
_T = TypeVar("_T")

SENTRY_DEFAULT_DSN = (
    "https://2592b1968ea94cca9b5ef5e348e094a7@o151352.ingest.sentry.io/4504800232407040"
)

SessionStatus = Literal["ok", "exited", "crashed", "abnormal"]


def _guard(
    method: Callable[Concatenate[Sentry, _P], _T],
) -> Callable[Concatenate[Sentry, _P], _T | None]:
    """Make a Sentry method safe, lazy, and non-raising.

    The wrapped method becomes a no-op if Sentry is disabled,
    this instance belongs to a different PID, or lazy boot fails
    """

    @functools.wraps(method)
    def wrapper(
        self: Sentry,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T | None:
        if not self._enabled:
            return None

        # If this instance belongs to a different process (fork happened),
        # do nothing; get_sentry() will create a fresh instance for the child.
        if self._pid != os.getpid():
            return None

        if not self._booted and not self._boot():
            return None

        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            if method.__name__ != "exception":
                # Best-effort logging of wrapper-level failures.
                with contextlib.suppress(Exception):
                    self.exception(f"Error in {method.__name__}: {e}")
            return None

    return wrapper


class Sentry:
    def __init__(self, *, pid: int) -> None:
        from wandb import env as _env

        self._pid: int = pid
        self._enabled: bool = bool(_env.error_reporting_enabled())
        self._booted: bool = False
        self._boot_lock = threading.Lock()
        self._atexit_registered: bool = False

        self._sent_messages: set[str] = set()
        self._sdk: Any | None = None  # will hold the sentry_sdk module after boot
        self.scope: Any | None = None

        self.dsn: str | None = os.environ.get(_env.SENTRY_DSN, SENTRY_DEFAULT_DSN)

    @property
    def environment(self) -> str:
        is_git = pathlib.Path(__file__).parent.parent.parent.joinpath(".git").exists()
        return "development" if is_git else "production"

    def _boot(self) -> bool:
        """Import sentry_sdk and set up client/scope."""
        from wandb import __version__

        with self._boot_lock:
            if not self._enabled:
                return False

            if self._booted:
                return True

            try:
                import sentry_sdk  # type: ignore
                import sentry_sdk.scope  # type: ignore
                import sentry_sdk.utils  # type: ignore

                self._sdk = sentry_sdk

                client = self._sdk.Client(
                    dsn=self.dsn,
                    default_integrations=False,
                    environment=self.environment,
                    release=__version__,
                )
                scope = self._sdk.get_global_scope().fork()
                scope.clear()
                scope.set_client(client)

                self.scope = scope
                self._booted = True

                if not self._atexit_registered:
                    atexit.register(self.end_session)
                    self._atexit_registered = True

            except Exception:
                # Disable on any failure.
                self._enabled = False
                self._booted = False
                self._sdk = None
                self.scope = None

                return False

            return True

    @_guard
    def message(
        self,
        message: str,
        repeat: bool = True,
        level: str = "info",
    ) -> str | None:
        if not repeat and message in self._sent_messages:
            return None
        self._sent_messages.add(message)
        with self._sdk.scope.use_isolation_scope(self.scope):  # type: ignore
            return self._sdk.capture_message(message, level=level)  # type: ignore

    @_guard
    def exception(
        self,
        exc: str
        | BaseException
        | tuple[
            type[BaseException] | None,
            BaseException | None,
            TracebackType | None,
        ]
        | None,
        handled: bool = False,
        status: SessionStatus | None = None,
    ) -> str | None:
        if isinstance(exc, str):
            exc_info = self._sdk.utils.exc_info_from_error(Exception(exc))  # type: ignore
        elif isinstance(exc, BaseException):
            exc_info = self._sdk.utils.exc_info_from_error(exc)  # type: ignore
        else:
            exc_info = sys.exc_info()

        event, _ = self._sdk.utils.event_from_exception(  # type: ignore
            exc_info,
            client_options=self.scope.get_client().options,  # type: ignore
            mechanism={"type": "generic", "handled": handled},
        )
        event_id = None
        with contextlib.suppress(Exception):
            with self._sdk.scope.use_isolation_scope(self.scope):  # type: ignore
                event_id = self._sdk.capture_event(event)  # type: ignore

        status = status or ("crashed" if not handled else "errored")  # type: ignore
        self.mark_session(status=status)

        client = self.scope.get_client()  # type: ignore
        if client is not None:
            client.flush()
        return event_id

    def reraise(self, exc: Any) -> Never:
        """Re-raise after logging, preserving traceback. Safe if disabled."""
        try:
            self.exception(exc)  # @_guard applies here
        finally:
            _, _, tb = sys.exc_info()
            if tb is not None and hasattr(exc, "with_traceback"):
                raise exc.with_traceback(tb)
            raise exc

    @_guard
    def start_session(self) -> None:
        if self.scope is None:
            return
        if self.scope._session is None:
            self.scope.start_session()

    @_guard
    def end_session(self) -> None:
        if self.scope is None:
            return
        client = self.scope.get_client()
        session = self.scope._session
        if session is not None and client is not None:
            self.scope.end_session()
            client.flush()

    @_guard
    def mark_session(self, status: SessionStatus | None = None) -> None:
        if self.scope is None:
            return
        session = self.scope._session
        if session is not None:
            session.update(status=status)

    @_guard
    def configure_scope(
        self,
        tags: dict[str, Any] | None = None,
        process_context: str | None = None,
    ) -> None:
        import wandb.util

        if self.scope is None:
            return

        settings_tags = (
            "entity",
            "project",
            "run_id",
            "run_url",
            "sweep_url",
            "sweep_id",
            "deployment",
            "launch",
            "_platform",
        )

        if process_context:
            self.scope.set_tag("process_context", process_context)

        if tags is None:
            return None

        for tag in settings_tags:
            val = tags.get(tag, None)
            if val not in (None, ""):
                self.scope.set_tag(tag, val)

        if tags.get("_colab", None):
            python_runtime = "colab"
        elif tags.get("_jupyter", None):
            python_runtime = "jupyter"
        elif tags.get("_ipython", None):
            python_runtime = "ipython"
        else:
            python_runtime = "python"
        self.scope.set_tag("python_runtime", python_runtime)

        # Construct run_url and sweep_url given run_id and sweep_id.
        for obj in ("run", "sweep"):
            obj_id, obj_url = f"{obj}_id", f"{obj}_url"
            if tags.get(obj_url, None):
                continue
            try:
                app_url = wandb.util.app_url(tags["base_url"])  # type: ignore[index]
                entity, project = (quote(tags[k]) for k in ("entity", "project"))  # type: ignore[index]
                self.scope.set_tag(
                    obj_url,
                    f"{app_url}/{entity}/{project}/{obj}s/{tags[obj_id]}",
                )
            except Exception:
                pass

        email = tags.get("email")
        if email:
            self.scope.user = {"email": email}

        self.start_session()


_singleton: Sentry | None = None
_singleton_lock = threading.Lock()


def get_sentry() -> Sentry:
    """Return the Sentry singleton for the current process (fork-aware).

    Creates a new instance in child processes after fork.
    Thread-safe within each process.
    """
    global _singleton

    pid = os.getpid()

    with _singleton_lock:
        if _singleton is not None and _singleton._pid == pid:
            return _singleton

        if _singleton is None or _singleton._pid != pid:
            _singleton = Sentry(pid=pid)

        return _singleton
