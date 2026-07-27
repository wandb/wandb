"""W&B Public API for Sweeps.

This module provides classes for interacting with W&B hyperparameter
optimization sweeps.

Example:
```python
from wandb.apis.public import Api

# Get a specific sweep
sweep = Api().sweep("entity/project/sweep_id")

# Access sweep properties
print(f"Sweep: {sweep.name}")
print(f"State: {sweep.state}")
print(f"Best Loss: {sweep.best_loss}")

# Get best performing run
best_run = sweep.best_run()
print(f"Best Run: {best_run.name}")
print(f"Metrics: {best_run.summary}")
```

Note:
    This module is part of the W&B Public API and provides read-only access
    to sweep data. For creating and controlling sweeps, use the wandb.sweep()
    and wandb.agent() functions from the main wandb package.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import random
import sys
import threading
import time
import urllib
import weakref
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from typing_extensions import override

import wandb
from wandb import util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.paginator import SizedPaginator
from wandb.errors import Error, UnsupportedError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import ipython

# Minimum W&B server release that supports filtering sweeps via the `filters`
# argument on the `sweeps` field.
_SWEEP_FILTERS_MIN_SERVER_VERSION = "0.81.4"

if TYPE_CHECKING:
    import requests

    from wandb.apis._generated import GetSweeps
    from wandb.apis.public.api import Api
    from wandb.apis.public.runs import AgentRuns
    from wandb.apis.public.service_api import ServiceApi

logger = logging.getLogger(__name__)


class Sweeps(SizedPaginator["Sweep"]):
    """A lazy iterator over a collection of `Sweep` objects.

    Examples:
    ```python
    from wandb.apis.public import Api

    sweeps = Api().project(name="project_name", entity="entity").sweeps()

    # Iterate over sweeps and print details
    for sweep in sweeps:
        print(f"Sweep name: {sweep.name}")
        print(f"Sweep ID: {sweep.id}")
        print(f"Sweep URL: {sweep.url}")
        print("----------")
    ```
    """

    QUERY: ClassVar[str | None] = None
    last_response: GetSweeps | None

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        project: str,
        per_page: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> None:
        """An iterable collection of `Sweep` objects.

        Args:
            service_api: The service API used to query W&B.
            entity: The entity which owns the sweeps.
            project: The project which contains the sweeps.
            per_page: The number of sweeps to fetch per request to the API.
            filters: (dict) queries for specific sweeps using the runs filters,
                See wandb/apis/public/api.py:runs for more details.
        """
        if self.QUERY is None:
            from wandb.apis._generated import GET_SWEEPS_GQL

            type(self).QUERY = GET_SWEEPS_GQL

        self.entity = entity
        self.project = project
        self._service_api = service_api
        self._supports_filtering = service_api.feature_enabled(
            pb.SWEEPS_QUERY_FILTERING
        )

        # Fail fast if the caller requested filtering but the
        # server can't honor it, rather than silently returning unfiltered sweeps.
        if filters and not self._supports_filtering:
            raise UnsupportedError(
                "Filtering sweeps is not supported on this W&B server version. "
                "Please upgrade your server to release "
                f"{_SWEEP_FILTERS_MIN_SERVER_VERSION} or later, or query sweeps "
                "on https://wandb.ai."
            )

        variables = {
            "project": self.project,
            "entity": self.entity,
            "filters": json.dumps(filters or {}),
        }
        super().__init__(service_api, variables, per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb.apis._generated import GetSweeps

        # On servers that don't support the `filters` argument, strip it from the
        # query so that listing sweeps still works.
        omit_variables = None if self._supports_filtering else ["filters"]
        self.last_response = self._service_api.execute_graphql(
            self.QUERY,
            variables=self.variables,
            omit_variables=omit_variables,
            parse=GetSweeps.model_validate_json,
        )

    @property
    @override
    def _length(self) -> int:
        """The total number of sweeps in the project.

        <!-- lazydoc-ignore -->
        """
        if not self.last_response:
            self._load_page()

        if not self.last_response or not self.last_response.project:
            return 0

        return self.last_response.project.total_sweeps

    @property
    @override
    def more(self) -> bool:
        """Returns whether there are more sweeps to fetch.

        <!-- lazydoc-ignore -->
        """
        if (
            self.last_response
            and self.last_response.project
            and self.last_response.project.sweeps
            and self.last_response.project.sweeps.page_info
        ):
            return self.last_response.project.sweeps.page_info.has_next_page

        return True

    @property
    @override
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of sweeps.

        <!-- lazydoc-ignore -->
        """
        if (
            self.last_response
            and self.last_response.project
            and self.last_response.project.sweeps
            and self.last_response.project.sweeps.page_info
        ):
            return self.last_response.project.sweeps.page_info.end_cursor

        return None

    @override
    def convert_objects(self) -> list[Sweep]:
        """Converts the last GraphQL response into a list of `Sweep` objects.

        <!-- lazydoc-ignore -->
        """
        from wandb._pydantic import Connection
        from wandb.apis._generated import SweepFragment

        if (rsp := self.last_response) is None or (project := rsp.project) is None:
            msg = f"Could not find project {self.project!r}"
            raise ValueError(msg)

        if project.total_sweeps < 1:
            return []
        return [
            Sweep(
                self._service_api,
                self.entity,
                self.project,
                node.name,
            )
            for node in Connection[SweepFragment].model_validate(project.sweeps).nodes()
        ]

    def __repr__(self):
        return f"<Sweeps {self.entity}/{self.project}>"


def _get_sweep(
    service_api: ServiceApi,
    entity: str | None = None,
    project: str | None = None,
    sid: str | None = None,
    order: str | None = None,
    query: str | None = None,
    **kwargs: Any,
) -> Sweep | None:
    """Fetch a sweep using an already-owned service API."""
    from wandb.apis._generated import GET_SWEEP_GQL, GET_SWEEP_LEGACY_GQL

    if not order:
        order = "+created_at"

    variables = {"entity": entity, "project": project, "name": sid, **kwargs}
    if query is None:
        query = GET_SWEEP_GQL
    try:
        data = service_api.execute_graphql(query, variables=variables)
    except Exception:
        # Don't handle exception, rely on legacy query
        # TODO(gst): Implement updated introspection workaround
        query = GET_SWEEP_LEGACY_GQL
        data = service_api.execute_graphql(query, variables=variables)

    # FIXME: looks like this method allows passing arbitrary GQL queries, so for now
    # we'll have to skip trying to validate the result with a generated pydantic model.
    if not (
        data
        and (proj_dict := data.get("project"))
        and (sweep_dict := proj_dict.get("sweep"))
    ):
        return None
    sweep = Sweep(
        service_api,
        entity,
        project,
        sid,
        attrs=sweep_dict,
    )
    sweep.runs = public.Runs(
        service_api,
        entity,
        project,
        order=order,
        per_page=10,
        filters={"$and": [{"sweep": sweep.id}]},
    )
    return sweep


class _StructuredLogLine:
    """A single console log record in the server's structured (JSON) format."""

    __slots__ = ("content", "ts", "level", "label")

    def __init__(
        self,
        content: str,
        *,
        ts: str = "",
        level: str = "",
        label: str = "",
    ) -> None:
        self.content = content
        self.ts = ts
        self.level = level
        self.label = label

    def to_json(self) -> str:
        """Return the compact JSON encoding the filestream expects."""
        record: dict[str, str] = {
            "ts": self.ts,
            "content": self.content,
            "level": self.level,
            "label": self.label,
        }
        record = {k: v for k, v in record.items() if v}  # remove empty fields
        return json.dumps(record, separators=(",", ":"))


class _SweepLogStream:
    """Background sender that streams `Sweep.log()` console lines.

    Batches log lines and POSTs them to the sweep controller run's filestream
    endpoint from a daemon thread, so callers never block on the network.

    - never sends heartbeats or a completion/exit-code message, since it does
      not own the run's lifecycle, and
    - self-throttles: it paces posts to a minimum interval and backs that
      interval off when the server returns HTTP 429, dropping lines rather than
      blocking the caller indefinitely under sustained rate limiting.
    """

    _MAX_ITEMS_PER_POST = 10_000
    _MAX_RETRIES = 2
    _DEFAULT_INTERVAL = 2.0
    _MAX_INTERVAL = 60.0
    _IDLE_POLL = 0.2
    _FINISH_TIMEOUT = 10.0

    def __init__(self, session: requests.Session, endpoint: str) -> None:
        self._session = session
        self._endpoint = endpoint
        self._queue: queue.Queue[str] = queue.Queue()
        self._interval = self._DEFAULT_INTERVAL
        # Dedicated RNG for retry jitter: isolated from global random.seed()
        # and not shared across sender threads.
        self._rng = random.Random()
        # Local monotonic line offset. The backend reassigns real offsets for
        # the co-owned controller run, so this is only meaningful for local
        # debugging of the outgoing payloads.
        self._offset = 0
        self._dropped = 0
        self._warned = False
        self._stop = threading.Event()
        self._lock = threading.Lock()  # mutex over started and finished
        self._started = False
        self._finished = False
        self._thread = threading.Thread(
            target=self._run, name="SweepLogStream", daemon=True
        )

    def start(self) -> None:
        """Start the background sender thread (idempotent)."""
        with self._lock:
            if self._started:
                return
            self._started = True
        self._thread.start()
        atexit.register(self.finish)

    def push(self, lines: Iterable[str]) -> None:
        """Enqueue formatted log lines for delivery. Never blocks on I/O.

        Accepts any iterable (including a lazy generator) so callers can format
        lines on demand without materializing the whole batch in memory.
        """
        dropped = 0
        for line in lines:
            if self._stop.is_set():
                # Sender is shutting down; don't accept new lines.
                dropped += 1
                continue
            self._queue.put(line)
        if dropped:
            self._dropped += dropped

    def finish(self, timeout: float | None = None) -> None:
        """Flush queued lines and stop the sender thread (idempotent).

        Registered with `atexit` so trailing lines are delivered on process
        exit, and used as the `weakref` finalizer so a `Sweep` that goes out of
        scope tears down its thread.
        """
        with self._lock:
            if not self._started or self._finished:
                return
            self._finished = True
        self._stop.set()
        self._thread.join(timeout if timeout is not None else self._FINISH_TIMEOUT)
        try:
            atexit.unregister(self.finish)
        except Exception:
            pass

    # -- background thread ------------------------------------------------

    def _run(self) -> None:
        """Thread entry point: run the send loop under a crash safety net.

        Mirrors `FileStreamApi._thread_except_body`: an unhandled exception is
        logged and reported to Sentry rather than silently killing the sender.
        """
        try:
            self._loop()
        except Exception:
            logger.exception("Sweep.log() background sender thread crashed")
            try:
                from wandb.analytics import get_sentry

                get_sentry().exception(sys.exc_info())
            except Exception:
                pass

    def _loop(self) -> None:
        last_post = 0.0
        while True:
            batch = self._wait_for_batch()
            if batch is None:
                break  # stop requested and queue drained
            if not self._stop.is_set():
                # Pace posts to at most one per `_interval` seconds, collecting
                # any lines that arrive while we wait. Skipped while stopping so
                # shutdown flushes promptly.
                wait = self._interval - (time.monotonic() - last_post)
                if wait > 0:
                    self._stop.wait(wait)
                    batch.extend(
                        self._drain_available(self._MAX_ITEMS_PER_POST - len(batch))
                    )
            self._post_no_exception(batch)
            last_post = time.monotonic()

    def _wait_for_batch(self) -> list[str] | None:
        """Block for the next line, then drain up to a full batch."""
        first = self._wait_for_line()
        if first is None:
            return None
        batch = [first]
        batch.extend(self._drain_available(self._MAX_ITEMS_PER_POST - 1))
        return batch

    def _wait_for_line(self) -> str | None:
        """Return the next queued line, or None once stopped and drained."""
        while True:
            try:
                return self._queue.get(timeout=self._IDLE_POLL)
            except queue.Empty:
                if self._stop.is_set():
                    return None

    def _drain_available(self, limit: int) -> list[str]:
        items: list[str] = []
        while len(items) < limit:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _on_retry(self, status_code: int, _err_str: str) -> None:
        # Invoked by request_with_retry (on this thread) on each retry.
        if status_code == 429:
            backed_off = min(self._interval * 2, self._MAX_INTERVAL)
            # Equal jitter: keep half of the backed-off interval and randomize
            # the other half, so many senders throttled by the same rate-limit
            # event don't resynchronize onto an identical retry cadence.
            self._interval = backed_off / 2 + self._rng.random() * (backed_off / 2)

    def _post_no_exception(self, lines: list[str]) -> None:
        """Deliver a batch of lines to the sweep controller run."""
        try:
            self._post_batch(lines)
        except Exception as e:
            # An unexpected error delivering one batch causes it to drop.
            self._record_drop(len(lines), e)

    def _post_batch(self, lines: list[str]) -> None:
        from wandb.sdk.internal.file_stream import request_with_retry
        from wandb.sdk.lib.file_stream_utils import split_files
        from wandb.sdk.lib.filenames import OUTPUT_FNAME

        offset = self._offset
        self._offset += len(lines)

        # Split into sub-payloads under the backend's max size, exactly as
        # FileStreamApi._send does, so a large batch isn't rejected wholesale.
        files = {OUTPUT_FNAME: {"offset": offset, "content": lines}}
        for volume in split_files(files, max_bytes=util.MAX_LINE_BYTES):
            if not any(f.get("content") for f in volume.values()):
                # split_files can emit a trailing empty volume; skip it.
                continue
            response = request_with_retry(
                self._session.post,
                self._endpoint,
                json={"files": volume, "dropped": self._dropped},
                max_retries=self._MAX_RETRIES,
                retry_callback=self._on_retry,
            )
            if isinstance(response, Exception):
                dropped = sum(len(f["content"]) for f in volume.values())
                self._record_drop(dropped, response)
                continue
            self._apply_limits(response)

    def _record_drop(self, count: int, err: object) -> None:
        """Count undelivered lines and warn the user once."""
        self._dropped += count
        logger.warning("Sweep.log() dropped %d line(s): %s", count, err)
        if not self._warned:
            self._warned = True
            wandb.termwarn(
                "Some sweep log lines could not be delivered and were dropped "
                "(see the wandb debug log for details).",
                repeat=False,
            )

    def _apply_limits(self, response: requests.Response) -> None:
        """Adjust the post interval from the server's rate-limit response."""
        parsed: Any = None
        try:
            parsed = response.json()
        except Exception:
            pass
        limits = parsed.get("limits") if isinstance(parsed, dict) else None
        if isinstance(limits, dict):
            # Best-effort: honor a server-provided minimum seconds-between-posts
            # if present under a recognized key.
            for key in ("rate_limit_seconds", "min_post_interval_seconds"):
                value = limits.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    self._interval = min(
                        max(self._interval, float(value)), self._MAX_INTERVAL
                    )
                    return
        # No explicit guidance: relax the interval back toward the default.
        self._interval = max(self._DEFAULT_INTERVAL, self._interval * 0.9)


class Sweep(Attrs):
    """The set of runs associated with the sweep.

    Attributes:
        runs (Runs): List of runs
        id (str): Sweep ID
        project (str): The name of the project the sweep belongs to
        config (dict): Dictionary containing the sweep configuration
        state (str): The state of the sweep. Can be "Finished", "Failed",
            "Crashed", or "Running".
        expected_run_count (int): The number of expected runs for the sweep
    """

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        project: str,
        sweep_id: str,
        attrs: Mapping[str, Any] | None = None,
    ):
        # TODO: Add agents / flesh this out.
        super().__init__(dict(attrs or {}))
        self._entity = entity
        self.project = project
        self.id = sweep_id
        self._service_api = service_api
        self.runs = []

        # Lazily-built background log sender for `Sweep.log()`.
        self._log_stream: _SweepLogStream | None = None
        # Cached STRUCTURED_CONSOLE_LOGS server-feature check for `Sweep.log()`.
        self._structured_console_logs: bool | None = None

        self.load(force=not attrs)

    @property
    def entity(self) -> str:
        """The entity associated with the sweep."""
        return self._entity

    @property
    def username(self) -> str:
        """Deprecated. Use `Sweep.entity` instead."""
        wandb.termwarn("Sweep.username is deprecated. please use Sweep.entity instead.")
        return self._entity

    @property
    def config(self):
        """The sweep configuration used for the sweep."""
        return util.load_yaml(self._attrs["config"])

    def load(self, force: bool = False):
        """Fetch and update sweep data logged to the run from GraphQL database.

        <!-- lazydoc-ignore -->
        """
        if force or not self._attrs:
            if not (
                sweep := _get_sweep(
                    self._service_api,
                    self.entity,
                    self.project,
                    self.id,
                )
            ):
                raise ValueError(f"Could not find sweep {self!r}")
            self._attrs = sweep._attrs
            self.runs = sweep.runs

        return self._attrs

    @property
    def order(self):
        """Return the order key for the sweep."""
        if self._attrs.get("config") and self.config.get("metric"):
            sort_order = self.config["metric"].get("goal", "minimize")
            prefix = "+" if sort_order == "minimize" else "-"
            return public.QueryGenerator.format_order_key(
                prefix + self.config["metric"]["name"]
            )

    def best_run(self, order=None):
        """Return the best run sorted by the metric defined in config or the order passed in."""
        if order is None:
            order = self.order
        else:
            order = public.QueryGenerator.format_order_key(order)
        if order is None:
            wandb.termwarn(
                "No order specified and couldn't find metric in sweep config, returning most recent run"
            )
        else:
            wandb.termlog("Sorting runs by {}".format(order))
        filters = {"$and": [{"sweep": self.id}]}
        try:
            return public.Runs(
                self._service_api,
                self.entity,
                self.project,
                order=order,
                filters=filters,
                per_page=1,
            )[0]
        except IndexError:
            return None

    @property
    def expected_run_count(self) -> int | None:
        """Return the number of expected runs in the sweep or None for infinite runs."""
        return self._attrs.get("runCountExpected")

    @property
    def controller_run_name(self) -> str | None:
        """Name of the sweep's controller run, or None if unavailable."""
        return self._attrs.get("controllerRunName") or None

    @property
    def path(self):
        """Returns the path of the project.

        The path is a list containing the entity, project name, and sweep ID."""
        return [
            urllib.parse.quote_plus(self.entity),
            urllib.parse.quote_plus(self.project),
            urllib.parse.quote_plus(self.id),
        ]

    @property
    def url(self):
        """The URL of the sweep.

        The sweep URL is generated from the entity, project, the term
        "sweeps", and the sweep ID.run_id. For
        SaaS users, it takes the form
        of `https://wandb.ai/entity/project/sweeps/sweeps_ID`.
        """
        path = self.path
        path.insert(2, "sweeps")
        return self._service_api.app_url + "/".join(path)

    @property
    def name(self):
        """The name of the sweep.

        Returns the first name that exists in the following priority order:

        1. User-edited display name
        2. Name configured at creation time
        3. Sweep ID
        """
        return self._attrs.get("displayName") or self.config.get("name") or self.id

    @classmethod
    def get(
        cls,
        api: Api,
        entity: str | None = None,
        project: str | None = None,
        sid: str | None = None,
        order: str | None = None,
        query: str | None = None,
        **kwargs,
    ):
        """Execute a query against the cloud backend.

        Args:
            api: The W&B API instance.
            entity: The entity (username or team) that owns the project.
            project: The name of the project to fetch sweep from.
            sid: The sweep ID to query.
            order: The order in which the sweep's runs are returned.
            query: The query to use to execute the query.
            **kwargs: Additional keyword arguments to pass to the query.
        """
        return api._get_sweep(
            entity,
            project,
            sid,
            order=order,
            query=query,
            **kwargs,
        )

    def _make_sweep_agent(self, attrs: Mapping[str, Any]) -> Agent:
        """Construct `Agent` from API payload."""
        try:
            return Agent(
                self._service_api,
                attrs=attrs,
                entity=self.entity,
                project=self.project,
                sweep_id=self.id,
            )
        except ValueError as e:
            raise Error(
                "Sweep agent data from the W&B API was incomplete or invalid.",
                context={"details": str(e)},
            ) from e

    def agent(self, agent_id: str) -> Agent:
        """Query an agent by ID for this sweep.

        Args:
            agent_id: The ID of the agent to look up.
        """
        from wandb.apis._generated import GET_SWEEP_AGENT_GQL

        variables = {
            "agentID": agent_id,
            "sweep": self.id,
            "entity": self.entity,
            "project": self.project,
        }
        data = self._service_api.execute_graphql(
            GET_SWEEP_AGENT_GQL,
            variables=variables,
        )
        return self._make_sweep_agent(data["project"]["sweep"]["agent"])

    def agents(self) -> list[Agent]:
        """Query the list of all agents for this sweep."""
        from wandb.apis._generated import GET_SWEEP_AGENTS_GQL, GetSweepAgents

        variables = {
            "sweep": self.id,
            "entity": self.entity,
            "project": self.project,
        }
        parsed = self._service_api.execute_graphql(
            GET_SWEEP_AGENTS_GQL,
            variables=variables,
            parse=GetSweepAgents.model_validate_json,
        )
        if not parsed.project or not parsed.project.sweep:
            return []
        return [
            self._make_sweep_agent(edge.node.model_dump(by_alias=True))
            for edge in parsed.project.sweep.agents.edges
        ]

    def log(
        self,
        data: str | list[str] | Mapping[str, Any],
        *,
        add_timestamps: bool = True,
    ) -> None:
        """Write to the sweep's controller run, dispatching on the input type.

        The behavior depends on the type of `data`:

        - A `str` or `list[str]` appends console log lines to the controller
          run's `output.log` file.
        - A `Mapping` (dict) logs metrics to the controller run's history,
          using the same format as `wandb.Run.log()`. This branch is not yet
          implemented.

        Args:
            data: The value to log to the sweep controller run.
            add_timestamps: Whether to prefix each console log line with an
                ISO-8601 UTC timestamp. Ignored when logging metrics history.

        Raises:
            NotImplementedError: If `data` is a mapping (history logging is not
                yet implemented).
            wandb.Error: If the sweep has no controller run available.
        """
        if isinstance(data, Mapping):
            # Dict input logs metrics to the controller run's history
            # (wandb-history.jsonl), matching the format of wandb.Run.log().
            raise NotImplementedError(
                "Logging metrics to the sweep controller run history is not "
                "yet implemented. Pass a string or list of strings to append "
                "console log lines instead."
            )

        self._log_lines(data, add_timestamps=add_timestamps)

    def _log_lines(self, lines: list[str] | str, add_timestamps: bool = True) -> None:
        raw_lines: Iterable[str] = (lines,) if isinstance(lines, str) else lines
        structured = self._supports_structured_console_logs()

        # Split into individual console lines and format them lazily
        formatted_lines = (
            self._format_log_line(segment, structured, add_timestamps)
            for line in raw_lines
            for segment in line.replace("\r", "").rstrip().splitlines()
        )

        # Resolve the sender before streaming so a missing controller run still
        # fails fast (before any line is enqueued).
        self._get_log_stream().push(formatted_lines)

    def _format_log_line(
        self, segment: str, structured: bool, add_timestamps: bool
    ) -> str:
        timestamp = ""
        if add_timestamps:
            # Match core's console timestamp: microsecond-precision UTC
            # with no offset suffix (e.g. "2024-01-02T03:04:05.678901").
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
        if structured:
            content = _StructuredLogLine(segment, ts=timestamp).to_json()
        elif timestamp:
            content = f"{timestamp} {segment}"
        else:
            content = segment
        return f"{content}\n"

    def _supports_structured_console_logs(self) -> bool:
        """Whether the server parses structured (JSON) console log lines."""
        if self._structured_console_logs is None:
            self._structured_console_logs = self._service_api.feature_enabled(
                pb.STRUCTURED_CONSOLE_LOGS
            )
        return self._structured_console_logs

    def _get_log_stream(self) -> _SweepLogStream:
        """Return the lazily-built background log sender for this sweep."""
        if self._log_stream is not None:
            return self._log_stream

        if (run_name := self.controller_run_name) is None:
            raise Error(
                f"Sweep {self.entity}/{self.project}/{self.id} has no "
                "controller run available; Sweep.log() requires a W&B server "
                "that supports sweep controller runs."
            )

        import requests

        from wandb.sdk.internal.internal_api import Api as InternalApi

        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project}
        )
        session = requests.Session()
        session.auth = api.request_auth
        session.headers.update(api.request_headers)
        session.proxies.update(api.request_proxies)
        endpoint = (
            f"{api.settings('base_url')}/files"
            f"/{self.entity}/{self.project}/{run_name}/file_stream"
        )

        stream = _SweepLogStream(session, endpoint)
        stream.start()

        self._log_stream = stream
        return stream

    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying this sweep."""
        url = self.url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button("sweep")
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_html_(self) -> str:
        return self.to_html()

    def __repr__(self) -> str:
        pathstr = "/".join(self.path)
        state = self._attrs.get("state", "Unknown State")
        return f"<Sweep {pathstr} ({state})>"

    def __enter__(self) -> Sweep:
        return self
    
    def __exit__(self, *exc) -> None:
        """Cleanup log stream if using context manager."""
        if self._log_stream is not None:
            self._log_stream.finish()


class Agent(Attrs):
    def __init__(
        self,
        service_api: ServiceApi,
        attrs: Mapping[str, Any],
        entity: str,
        project: str,
        sweep_id: str,
    ) -> None:
        super().__init__(dict(attrs or {}))
        self._entity = entity
        self._project = project
        self._sweep_id = sweep_id
        self._service_api = service_api

        if self._entity is None:
            raise ValueError(
                "Agent requires entity. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if self._project is None:
            raise ValueError(
                "Agent requires project. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if self._sweep_id is None:
            raise ValueError(
                "Agent requires sweep_id. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if not (self._attrs.get("name") or self._attrs.get("id")):
            if self._attrs.get("name") is None:
                raise ValueError("Agent is missing name.")
            if self._attrs.get("id") is None:
                raise ValueError("Agent is missing id.")
            raise ValueError("Agent is missing a usable name or id.")
        self._agent_key: str = self._attrs.get("name") or self._attrs.get("id")

    def runs(
        self,
        per_page: int = 50,
    ) -> AgentRuns:
        """Return a paginated collection of runs executed by this agent."""
        from wandb.apis.public.runs import AgentRuns

        total_runs = int(self._attrs.get("totalRuns") or 0)
        return AgentRuns(
            self._service_api,
            entity=self._entity,
            project=self._project,
            sweep_id=self._sweep_id,
            agent_key=self._agent_key,
            total_runs=total_runs,
            order="+created_at",
            per_page=per_page,
        )

    def __repr__(self) -> str:
        state = self._attrs.get("state", "Unknown State")
        name = self._attrs.get("id", "Unknown")
        return f"<Agent {name} ({state})>"
