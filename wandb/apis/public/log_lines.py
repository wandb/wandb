"""W&B Public API for run console log lines.

This module exposes a run's streamed console log (`logLines`) through the public
API.

Example:
```python
from wandb.apis.public import Api

run = Api().run("entity/project/run_id")

# Tail (single request) — good for crash diagnosis of a running run.
for line in run.log_lines(last=200):
    print(line.line)

# Full forward pagination.
for line in run.log_lines():
    print(line.number, line.line)
```

Note:
    For a finished or crashed run, downloading `output.log` via `run.files()`
    is usually faster (one static file). Prefer `log_lines()` for a run that is
    still running (no file yet) or for a cheap tail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.apis.attrs import Attrs
from wandb.apis.paginator import SizedPaginator

if TYPE_CHECKING:
    from wandb.apis.public.runs import Run
    from wandb.apis.public.service_api import ServiceApi

LOG_LINES_FRAGMENT = """fragment RunLogLinesFragment on Run {
    logLines(first: $first, after: $after, last: $last) {
        edges {
            node {
                number
                timestamp
                level
                label
                line
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""


class LogLines(SizedPaginator["LogLine"]):
    """A lazy iterator over a run's console log lines.

    Backed by the `logLines` connection, fetched page-by-page. Length is the
    run's `logLineCount`.
    """

    def _get_query(self) -> str:
        return f"""#graphql
            query RunLogLines($project: String!, $entity: String!, $name: String!,
                $first: Int, $after: String, $last: Int) {{
                project(name: $project, entityName: $entity) {{
                    run(name: $name) {{
                        logLineCount
                        ...RunLogLinesFragment
                    }}
                }}
            }}
            {LOG_LINES_FRAGMENT}
            """

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
            per_page (int): Number of lines to fetch per page during forward
                pagination.
            last (int, optional): If set, fetch only the last N lines in a single
                request (a tail) instead of paginating from the start.
        """
        self.run = run
        self._tail = last
        variables = {
            "project": run.project,
            "entity": run.entity,
            "name": run.id,
            "last": last,
        }
        super().__init__(service_api, variables, per_page)

    def _update_response(self) -> None:
        """Fetch and store the response data for the next page."""
        self.last_response = self._service_api.execute_graphql(
            self._get_query(), variables=self.variables
        )

    def _run_node(self) -> dict:
        if not self.last_response:
            return {}
        return (self.last_response.get("project") or {}).get("run") or {}

    @property
    def _length(self) -> int:
        """Number of log lines this iterator yields.

        Forward pagination reports the run's total `logLineCount`; tail mode
        (`last=N`) reports only the size of the fetched tail, matching what
        iteration returns.
        """
        if not self.last_response:
            self._load_page()
        run_node = self._run_node()
        if self._tail is not None:
            conn = run_node.get("logLines") or {}
            return len(conn.get("edges") or [])
        return run_node.get("logLineCount", 0)

    @property
    def more(self) -> bool:
        """Whether there are more log lines to fetch."""
        # Tail mode is a single request: fetch once, then stop.
        if self._tail is not None:
            return self.last_response is None
        if not self.last_response:
            return True
        conn = self._run_node().get("logLines") or {}
        return (conn.get("pageInfo") or {}).get("hasNextPage", False)

    @property
    def cursor(self) -> str | None:
        """The end cursor of the last fetched page."""
        conn = self._run_node().get("logLines") or {}
        edges = conn.get("edges") or []
        return edges[-1].get("cursor") if edges else None

    def update_variables(self) -> None:
        """Update the GraphQL variables for the next page fetch."""
        if self._tail is not None:
            self.variables.update({"first": None, "after": None, "last": self._tail})
        else:
            self.variables.update(
                {"first": self.per_page, "after": self.cursor, "last": None}
            )

    def convert_objects(self) -> list[LogLine]:
        """Convert GraphQL edges to `LogLine` objects."""
        conn = self._run_node().get("logLines") or {}
        edges = conn.get("edges") or []
        return [LogLine(edge["node"]) for edge in edges]

    def __repr__(self) -> str:
        return f"<LogLines {'/'.join(self.run.path)} ({len(self)})>"


class LogLine(Attrs):
    """A single console log line from a run.

    Attributes (via `Attrs`):
        number (int): Line number (0-indexed).
        timestamp (str): ISO timestamp.
        level (str): Log level (`info`, `error`, ...).
        label (str): Writer label distinguishing concurrent writers to the same
            run in shared mode — not the stdout/stderr stream (usually empty for
            single-writer runs).
        line (str): The log line content.
    """

    def __init__(self, attrs: dict):
        super().__init__(dict(attrs))

    def __repr__(self) -> str:
        line = (self._attrs.get("line") or "")[:60]
        return f"<LogLine {self._attrs.get('number')}: {line!r}>"
