"""Read runs from a local wandb directory, without a W&B server.

Every run writes a `.wandb` transaction log to its run directory. `LocalApi`
reads those logs, so it works for offline runs, for runs that have not been
synced, and for runs that are still writing. Reads go through wandb-core,
like `wandb.Api()`, but need no API key or network.

Example:
```python
from wandb.beta import LocalApi

api = LocalApi("./wandb")
for run in api.runs():
    print(run.name, run.state, run.summary.get("loss"))

run = api.run("abc123")
for row in run.history(keys=["loss"], last=10):
    print(row["_step"], row["loss"])
for line in run.console_logs(last=20):
    print(line.timestamp, line.content)
```
"""

from __future__ import annotations

import glob
import json
import os
import pathlib
from datetime import datetime, timezone
from typing import Any

from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public.console_logs import ConsoleLogLine, _parse_timestamp
from wandb.apis.public.service_api import ServiceApi
from wandb.errors.term import termwarn
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk import wandb_setup


class LocalApi:
    """Reads the runs in a local wandb directory.

    Args:
        wandb_dir: The wandb directory, e.g. `"./wandb"`. Defaults to the
            directory runs are written to under the current settings.
    """

    def __init__(self, wandb_dir: str | os.PathLike[str] | None = None) -> None:
        termwarn(
            "wandb.beta.LocalApi is experimental and may change"
            " or be removed in any release.",
            repeat=False,
        )
        settings = wandb_setup.singleton().settings.model_copy()
        self.wandb_dir = str(
            pathlib.Path(wandb_dir or settings.wandb_dir).expanduser().resolve()
        )
        self._service_api = ServiceApi(settings=settings)

    def __repr__(self) -> str:
        return f"<LocalApi {self.wandb_dir}>"

    @normalize_exceptions
    def runs(self) -> list[LocalRun]:
        """Returns the runs in the directory, newest first."""
        request = apb.ApiRequest(
            list_local_runs_request=apb.ListLocalRunsRequest(wandb_dir=self.wandb_dir)
        )
        response = self._service_api.send_api_request(request)
        return [
            LocalRun(self._service_api, info=info)
            for info in response.list_local_runs_response.runs
        ]

    def run(self, run: str | os.PathLike[str]) -> LocalRun:
        """Returns one run.

        Args:
            run: A run ID or run directory name inside the wandb directory,
                or a path to a run directory or `.wandb` file.

        Raises:
            FileNotFoundError: If there is no such run.
        """
        for candidate in (
            pathlib.Path(run).expanduser(),
            pathlib.Path(self.wandb_dir, run),
        ):
            if candidate.is_file() and candidate.suffix == ".wandb":
                return LocalRun(self._service_api, wandb_file=str(candidate.resolve()))
            if candidate.is_dir():
                files = list(candidate.glob("run-*.wandb"))
                if len(files) == 1:
                    return LocalRun(
                        self._service_api, wandb_file=str(files[0].resolve())
                    )

        # Run directories are named "<offline->run-<timestamp>-<id>"; the
        # newest of several with the same ID (a resumed run) wins.
        files = pathlib.Path(self.wandb_dir).glob(
            f"*run-*/run-{glob.escape(str(run))}.wandb"
        )
        newest = max(
            files,
            key=lambda file: file.parent.name.removeprefix("offline-"),
            default=None,
        )
        if newest is None:
            raise FileNotFoundError(f"no run {str(run)!r} in {self.wandb_dir}")
        return LocalRun(self._service_api, wandb_file=str(newest.resolve()))


class LocalRun:
    """A run read from its local transaction log.

    Attributes are read on first access and cached; call `refresh()` to read
    a still-running run's latest data.
    """

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        info: apb.LocalRunInfo | None = None,
        wandb_file: str | None = None,
    ) -> None:
        if wandb_file is None:
            if info is None:
                raise ValueError("info or wandb_file is required")
            wandb_file = info.wandb_file
        self._service_api = service_api
        self._info = info
        self._wandb_file = wandb_file
        self._details: apb.ReadLocalRunResponse | None = None

    def __repr__(self) -> str:
        return f"<LocalRun {os.path.basename(self.sync_dir)}>"

    @property
    def wandb_file(self) -> str:
        """The path of the run's `.wandb` transaction log."""
        return self._wandb_file

    @property
    def sync_dir(self) -> str:
        """The run's directory, which holds the transaction log and its files."""
        return os.path.dirname(self._wandb_file)

    def refresh(self) -> None:
        """Forgets cached data so the next attribute access reads the log again."""
        self._info = None
        self._details = None

    @normalize_exceptions
    def _load(self) -> apb.ReadLocalRunResponse:
        if self._details is None:
            request = apb.ApiRequest(
                read_local_run_request=apb.ReadLocalRunRequest(
                    wandb_file=self._wandb_file
                )
            )
            response = self._service_api.send_api_request(request)
            self._details = response.read_local_run_response
            self._info = self._details.info
        return self._details

    def _identity(self) -> apb.LocalRunInfo:
        return self._info if self._info is not None else self._load().info

    @property
    def id(self) -> str:
        return self._identity().run_id

    @property
    def name(self) -> str:
        """The run's display name."""
        return self._identity().display_name

    @property
    def entity(self) -> str:
        return self._identity().entity

    @property
    def project(self) -> str:
        return self._identity().project

    @property
    def notes(self) -> str:
        return self._identity().notes

    @property
    def tags(self) -> list[str]:
        return list(self._identity().tags)

    @property
    def group(self) -> str:
        return self._identity().group

    @property
    def job_type(self) -> str:
        return self._identity().job_type

    @property
    def sweep_id(self) -> str:
        return self._identity().sweep_id

    @property
    def host(self) -> str:
        return self._identity().host

    @property
    def offline(self) -> bool:
        """Whether the run was started in offline mode."""
        return self._identity().offline

    @property
    def start_time(self) -> datetime | None:
        info = self._identity()
        if not info.HasField("start_time"):
            return None
        return info.start_time.ToDatetime(tzinfo=timezone.utc)

    @property
    def state(self) -> str:
        """One of `pending`, `running`, `finished`, `failed` or `crashed`.

        `pending` means the run's first record has not been written yet. A run
        with no exit record whose log has not changed for 10 minutes counts as
        crashed.
        """
        return self._identity().state

    @property
    def config(self) -> dict[str, Any]:
        """The run's config, without W&B's internal `_wandb` entry."""
        config = json.loads(self._load().config_json or "{}")
        config.pop("_wandb", None)
        return config

    @property
    def summary(self) -> dict[str, Any]:
        return json.loads(self._load().summary_json or "{}")

    @property
    def metadata(self) -> dict[str, Any] | None:
        """The run's environment, the contents of wandb-metadata.json."""
        environment_json = self._load().environment_json
        return json.loads(environment_json) if environment_json else None

    @property
    def last_step(self) -> int:
        """The highest history step logged, or -1 if there is no history."""
        return self._load().last_step

    @property
    def history_keys(self) -> list[str]:
        return list(self._load().history_keys)

    @property
    def exit_code(self) -> int | None:
        """The run's exit code, or None while it has not exited."""
        details = self._load()
        return details.exit_code if details.HasField("exit_code") else None

    @normalize_exceptions
    def history(
        self,
        keys: list[str] | None = None,
        *,
        min_step: int | None = None,
        max_step: int | None = None,
        last: int | None = None,
    ) -> list[dict[str, Any]]:
        """Returns history rows, oldest first.

        Every row has `_step`. The log has no index, so each call reads the
        whole file.

        Args:
            keys: Return only these keys; rows with none of them are skipped.
            min_step: Return only rows at or after this step.
            max_step: Return only rows at or before this step.
            last: Return only the last N matching rows.
        """
        request = apb.ReadLocalRunHistoryRequest(
            wandb_file=self._wandb_file, keys=list(keys or [])
        )
        if min_step is not None:
            request.min_step = min_step
        if max_step is not None:
            request.max_step = max_step
        if last is not None:
            request.last = last
        response = self._service_api.send_api_request(
            apb.ApiRequest(read_local_run_history_request=request)
        )

        rows: list[dict[str, Any]] = []
        for row in response.read_local_run_history_response.rows:
            values: dict[str, Any] = {"_step": row.step}
            for item in row.items:
                values[item.key] = json.loads(item.value_json)
            rows.append(values)
        return rows

    @normalize_exceptions
    def console_logs(self, last: int | None = None) -> list[ConsoleLogLine]:
        """Returns the run's console output, oldest first.

        Args:
            last: Return only the last N lines.
        """
        request = apb.ReadLocalRunConsoleLogsRequest(wandb_file=self._wandb_file)
        if last is not None:
            request.last = last
        response = self._service_api.send_api_request(
            apb.ApiRequest(read_local_run_console_logs_request=request)
        )
        return [
            ConsoleLogLine(
                number=line.number,
                timestamp=_parse_timestamp(line.timestamp),
                level=line.level,
                label=line.label,
                content=line.content,
            )
            for line in response.read_local_run_console_logs_response.lines
        ]
