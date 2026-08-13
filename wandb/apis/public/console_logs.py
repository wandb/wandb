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

from wandb.apis.paginator import Paginator
from wandb.proto import wandb_api_pb2 as apb

if TYPE_CHECKING:
    from wandb.apis.public.runs import Run
    from wandb.apis.public.service_api import ServiceApi


@dataclass(frozen=True)
class ConsoleLogLine:
    """A single line of a run's captured console output.

    Attributes:
        number (int): Position of the line in the run's console log,
            starting at 0.
        timestamp (datetime): The time the line was captured, as a
            timezone-aware UTC datetime. None if the backend did not
            record a time for the line or sent one in an unexpected
            format.
        level (str): The severity of the line: `"error"` for lines written
            to stderr, `""` or `"info"` otherwise.
        label (str): A label identifying the process that wrote the line
            when several processes write to the same run, as set by the
            `x_label` setting in shared mode. Empty for single-writer
            runs.
        content (str): The text of the line.
    """

    number: int
    timestamp: datetime | None
    level: str
    label: str
    content: str


class ConsoleLogs(Paginator[ConsoleLogLine]):
    """A lazy iterator over a run's console log lines, oldest first.

    Fetched from the W&B backend page by page.
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
            per_page (int): Number of lines to fetch per request when
                reading the log from the beginning.
            last (int, optional): If set, fetch only the last N lines of
                the log in a single request instead of reading from the
                beginning. The backend returns at most 10,000 lines per
                request, so a larger tail comes back truncated to the
                newest 10,000 lines.
        """
        if last is not None and last <= 0:
            raise ValueError(f"last must be positive, got {last}")
        if per_page <= 0:
            raise ValueError(f"per_page must be positive, got {per_page}")

        self.run = run
        self._tail = last
        self._lines_fetched = 0
        self._total: int | None = None
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
        if self.last_response.has_next_page:
            return True
        # Defend against a backend page cut short by a server-side
        # per-request size budget, which can report has_next_page=False
        # in the middle of the log: keep reading while pages come back
        # non-empty and fewer lines than the log's total have been seen.
        return (
            len(self.last_response.lines) > 0
            and self._total is not None
            and self._lines_fetched < self._total
        )

    @property
    def cursor(self) -> str | None:
        """Returns an opaque cursor marking where the last page ended.

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
        if self._total is None:
            self._total = self.last_response.total_lines

    def convert_objects(self) -> list[ConsoleLogLine]:
        """Converts the last fetched response into `ConsoleLogLine`s.

        <!-- lazydoc-ignore -->
        """
        if self.last_response is None:
            return []
        self._lines_fetched += len(self.last_response.lines)
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
    # trailing "Z" and trim fractional seconds beyond microseconds.
    value = value.replace("Z", "+00:00").replace("z", "+00:00")
    if (dot := value.find(".")) != -1:
        end = dot + 1
        while end < len(value) and value[end].isdigit():
            end += 1
        value = value[: min(end, dot + 7)] + value[end:]
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # The backend records timestamps in UTC but omits the zone designator.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
