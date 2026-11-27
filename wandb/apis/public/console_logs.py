"""W&B Public API for reading a run's captured console output.

While a run is running, W&B captures what the process writes to stdout and
stderr and records it as the run's console log — the same log shown in the
"Logs" tab of the run page in the W&B App. This module reads that log back
through the public API.

Example:
```python
import wandb

run = wandb.Api().run("entity/project/run_id")

# Read the whole log, oldest line first.
for line in run.console_logs():
    print(line.content)

# Read only the last 100 lines — a cheap way to check on a live run
# or diagnose a crash.
for line in run.console_logs(last=100):
    print(line.timestamp, line.content)
```
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator
from wandb.proto import wandb_api_pb2 as apb

if TYPE_CHECKING:
    from wandb.apis.public.runs import Run
    from wandb.apis.public.service_api import ServiceApi


@dataclass(frozen=True)
class ConsoleLogLine:
    """A single line of a run's captured console output.

    Attributes:
        number: Position of the line in the run's console log,
            starting at 0.
        timestamp: The time the line was captured, as a
            timezone-aware UTC datetime. None if the backend did not
            record a time for the line or sent one in an unexpected
            format.
        level: The severity of the line: `"error"` for lines written
            to stderr, empty otherwise.
        label: A label identifying the process that wrote the line
            when several processes write to the same run, as set by the
            `x_label` setting in shared mode. Empty for single-writer
            runs.
        content: The text of the line.
    """

    number: int
    timestamp: datetime | None
    level: str
    label: str
    content: str


class ConsoleLogs(Paginator[ConsoleLogLine]):
    """A lazy iterator over a run's console log lines, oldest first.

    Fetched from the W&B backend page by page. Fetched lines are kept in
    memory, so iterating a second time replays the same lines instead of
    refetching; create a new instance to re-read a log that may have
    grown.
    """

    last_response: apb.ReadRunConsoleLogsResponse | None

    def __init__(
        self,
        service_api: ServiceApi,
        run: Run,
        per_page: int = 1000,
        last: int | None = None,
    ):
        """Initialize a lazy iterator over a run's console log lines.

        Args:
            service_api: The service API instance used to query W&B.
            run: The run whose console log is read.
            per_page: Number of lines to fetch per request when reading
                the log from the beginning. Ignored when `last` is given.
            last: If set, fetch only the last N lines of the log in a
                single request instead of reading from the beginning.
                The backend caps how many lines one request returns, so
                a larger tail comes back truncated to the newest lines.
        """
        self.run = run
        self._tail = last
        super().__init__(service_api, variables={}, per_page=per_page)

    @property
    def more(self) -> bool:
        """Returns whether there are more log lines to fetch.

        <!-- lazydoc-ignore -->
        """
        if self.last_response is None:
            return True
        # A tail is a single request: fetch once, then stop.
        if self._tail is not None:
            return False
        # Requiring a cursor guards against restarting from the start of
        # the log if a server ever claims a next page without saying
        # where it begins.
        return self.last_response.has_next_page and bool(self.last_response.end_cursor)

    @property
    def cursor(self) -> str | None:
        """Returns the cursor at which the last fetched page ended.

        A cursor is a bookmark string minted by the server: sending it
        back resumes reading right after the last line of the previous
        page. It is opaque — meaningful only to the server, with no
        format the client may inspect or construct.

        <!-- lazydoc-ignore -->
        """
        if self.last_response is None:
            return None
        return self.last_response.end_cursor or None

    def update_variables(self) -> None:
        """Updates the request parameters for the next page fetch.

        The request is built in `_update_response`, so there is nothing
        to update here.

        <!-- lazydoc-ignore -->
        """

    @normalize_exceptions
    def _update_response(self) -> None:
        """Fetches and stores the next page of console log lines."""
        request = apb.ReadRunConsoleLogsRequest(
            entity=self.run.entity,
            project=self.run.project,
            run_id=self.run.id,
        )
        if self._tail is not None:
            request.last = self._tail
        else:
            request.first = self.per_page
            if (after := self.cursor) is not None:
                request.after = after

        response = self._service_api.send_api_request(
            apb.ApiRequest(read_run_console_logs_request=request)
        )
        self.last_response = response.read_run_console_logs_response

    def convert_objects(self) -> list[ConsoleLogLine]:
        """Converts the last fetched response into `ConsoleLogLine`s.

        <!-- lazydoc-ignore -->
        """
        if self.last_response is None:
            return []
        return [
            ConsoleLogLine(
                number=line.number,
                timestamp=_parse_timestamp(line.timestamp),
                level=line.level,
                label=line.label,
                content=line.content,
            )
            for line in self.last_response.lines
        ]

    def __repr__(self) -> str:
        return f"<ConsoleLogs {self.run.entity}/{self.run.project}/{self.run.id}>"


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO 8601 / RFC 3339 timestamp, returning None on failure."""
    if not value:
        return None
    # datetime.fromisoformat is strict before Python 3.11: normalize the
    # trailing "Z" and force exactly six fractional-second digits.
    value = value.replace("Z", "+00:00").replace("z", "+00:00")
    if (dot := value.find(".")) != -1:
        end = dot + 1
        while end < len(value) and value[end].isdigit():
            end += 1
        fraction = value[dot + 1 : end][:6].ljust(6, "0")
        value = f"{value[:dot]}.{fraction}{value[end:]}"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # The backend records timestamps in UTC but omits the zone designator.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
