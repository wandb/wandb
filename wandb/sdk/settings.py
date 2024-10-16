from __future__ import annotations

import datetime
import logging
import os
import platform
import sys
import tempfile
import time
from typing import Literal, Sequence
from urllib.parse import quote, unquote, urlencode

from pydantic import AnyHttpUrl, BaseModel, Field, computed_field, field_validator

from wandb import termwarn, util
from wandb.apis.internal import Api
from wandb.errors import UsageError

from .lib import apikey
from .lib.ipython import _get_python_type


def now() -> str:
    datetime_now = datetime.datetime.fromtimestamp(time.time())
    return datetime_now.strftime("%Y%m%d_%H%M%S")


class Settings(BaseModel, validate_assignment=True):
    """Settings for W&B."""

    # ???
    _cli_only_mode: bool = False
    # Do not collect system metadata
    _disable_meta: bool = False
    # Do not collect system stats
    _disable_stats: bool = False
    # Do not collect system metrics
    _disable_service: bool = False
    # Do not use setproctitle on internal process
    _disable_setproctitle: bool = False
    # Do not collect system metrics
    _disable_stats: bool = False
    # Disable version check
    _disable_update_check: bool = False
    # Prevent early viewer query
    _disable_viewer: bool = False
    # Disable automatic machine info collection
    _disable_machine_info: bool = False
    _extra_http_headers: dict[str, str] | None = None
    # max size for filestream requests in core
    _file_stream_max_bytes: int | None = None
    # tx interval for filestream requests in core
    _file_stream_transmit_interval: float | None = None
    # file stream retry client configuration
    # max number of retries
    _file_stream_retry_max: int | None = None
    # min wait time between retries
    _file_stream_retry_wait_min_seconds: float | None = None
    # max wait time between retries
    _file_stream_retry_wait_max_seconds: float | None = None
    # timeout for individual HTTP requests
    _file_stream_timeout_seconds: float | None = None
    # file transfer retry client configuration
    _file_transfer_retry_max: int | None = None
    _file_transfer_retry_wait_min_seconds: float | None = None
    _file_transfer_retry_wait_max_seconds: float | None = None
    _file_transfer_timeout_seconds: float | None = None
    # graphql retry client configuration
    _graphql_retry_max: int | None = None
    _graphql_retry_wait_min_seconds: float | None = None
    _graphql_retry_wait_max_seconds: float | None = None
    _graphql_timeout_seconds: float | None = None
    _internal_check_process: float = 8.0
    _internal_queue_timeout: float = 2.0
    _jupyter_name: str | None = None
    _jupyter_path: str | None = None
    _jupyter_root: str | None = None
    _live_policy_rate_limit: int | None = None
    _live_policy_wait_time: int | None = None
    _log_level: int = logging.INFO
    _network_buffer: int | None = None
    # [deprecated, use http(s)_proxy] custom proxy servers for the requests to W&B [scheme -> url]
    _proxies: dict[str, str] | None = None
    _sync: bool = False
    api_key: str | None = None
    # The base URL for the W&B API.
    base_url: AnyHttpUrl = "https://api.wandb.ai"
    console: Literal["auto", "off", "wrap", "redirect", "wrap_raw", "wrap_emu"] = "auto"
    entity: str | None = None
    http_proxy: AnyHttpUrl | None = None
    https_proxy: AnyHttpUrl | None = None
    mode: Literal["online", "offline", "dryrun", "disabled", "run", "shared"] = "online"
    program: str | None = None
    project: str | None = None
    root_dir: str | None = None
    run_id: str | None = None
    start_datetime: str = Field(default_factory=now)
    sweep_id: str | None = None

    # Field validators.
    @field_validator("_disable_service", mode="before")
    @classmethod
    def validate_disable_service_before(cls, value):
        if value:
            termwarn(
                "Disabling the wandb service is deprecated as of version 0.18.0 and will be removed in future versions. ",
                repeat=False,
            )
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key_before(cls, value):
        if len(value) > len(value.strip()):
            raise UsageError("API key cannot start or end with whitespace")
        return value

    @field_validator("base_url", mode="before")
    @classmethod
    def validate_base_url(cls, value):
        return value.strip().rstrip("/")

    @field_validator("console", mode="after")
    @classmethod
    def validate_console(cls, value, info):
        if value != "auto":
            return value
        if (
            _get_python_type() == "jupyter"
            or (info.data.get("start_method") == "thread")
            or not info.data.get("_disable_service")
            or platform.system() == "Windows"
        ):
            value = "wrap"
        else:
            value = "redirect"
        return value

    @field_validator("program", mode="after")
    @classmethod
    def validate_program(cls, program, info):
        if program is not None and program != "<python with no main file>":
            return program

        if not _get_python_type() == "jupyter":
            return program

        notebook_name = info.data.get("notebook_name")
        if notebook_name:
            return notebook_name

        _jupyter_path = info.data.get("_jupyter_path")
        if not _jupyter_path:
            return program

        if _jupyter_path.startswith("fileId="):
            return info.data.get("_jupyter_name")
        else:
            return _jupyter_path

    @field_validator("project", mode="after")
    @classmethod
    def validate_project(cls, value):
        invalid_chars_list = list("/\\#?%:")
        if len(value) > 128:
            raise UsageError(f"Invalid project name {value!r}: exceeded 128 characters")
        invalid_chars = {char for char in invalid_chars_list if char in value}
        if invalid_chars:
            raise UsageError(
                f"Invalid project name {value!r}: "
                f"cannot contain characters {','.join(invalid_chars_list)!r}, "
                f"found {','.join(invalid_chars)!r}"
            )
        return value

    @field_validator("root_dir", mode="before")
    @classmethod
    def validate_root_dir(cls, value):
        return str(value) or os.path.abspath(os.getcwd())

    @field_validator("run_id", mode="after")
    @classmethod
    def validate_run_id(cls, value):
        if len(value) == 0:
            raise UsageError("Run ID cannot be empty")
        if len(value) > len(value.strip()):
            raise UsageError("Run ID cannot start or end with whitespace")
        if not bool(value.strip()):
            raise UsageError("Run ID cannot contain only whitespace")
        return value

    @field_validator("sweep_id", mode="after")
    @classmethod
    def validate_sweep_id(cls, value):
        if len(value) == 0:
            raise UsageError("Sweep ID cannot be empty")
        if len(value) > len(value.strip()):
            raise UsageError("Sweep ID cannot start or end with whitespace")
        if not bool(value.strip()):
            raise UsageError("Sweep ID cannot contain only whitespace")
        return value

    # Computed fields.
    @computed_field
    @property
    def _args(self) -> Sequence[str]:
        if not self._jupyter:
            return sys.argv[1:]
        return []

    @computed_field
    @property
    def _aws_lambda(self) -> bool:
        """Check if we are running in a lambda environment."""
        from sentry_sdk.integrations.aws_lambda import get_lambda_bootstrap

        lambda_bootstrap = get_lambda_bootstrap()
        if not lambda_bootstrap or not hasattr(
            lambda_bootstrap, "handle_event_request"
        ):
            return False
        return True

    @computed_field
    @property
    def _code_path_local(self) -> str:
        return self._get_program_relpath(self.program)

    @computed_field
    @property
    def _colab(self) -> bool:
        return "google.colab" in sys.modules

    @computed_field
    @property
    def _ipython(self) -> bool:
        return _get_python_type() == "ipython"

    @computed_field
    @property
    def _jupyter(self) -> bool:
        return _get_python_type() == "jupyter"

    @computed_field
    @property
    def _kaggle(self) -> bool:
        return util._is_likely_kaggle()

    @computed_field
    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

    @computed_field
    @property
    def _notebook(self) -> bool:
        return self._ipython or self._jupyter or self._colab or self._kaggle

    @computed_field
    @property
    def _offline(self) -> bool:
        return self.mode in ("offline", "dryrun")

    @computed_field
    @property
    def _os(self) -> str:
        return platform.platform(aliased=True)

    @computed_field
    @property
    def _platform(self) -> str:
        return f"{platform.system()}-{platform.machine()}".lower()

    @computed_field
    @property
    def _python(self) -> str:
        return f"{platform.python_implementation()} {platform.python_version()}"

    @computed_field
    @property
    def _shared(self) -> bool:
        return self.mode == "shared"

    @computed_field
    @property
    def _tmp_code_dir(self) -> str:
        return self._path_convert(self.wandb_dir, "code")

    @computed_field
    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @computed_field
    @property
    def colab_url(self) -> AnyHttpUrl | None:
        if not self._colab:
            return None
        if self._jupyter_path and self._jupyter_path.startswith("fileId="):
            unescaped = unquote(self._jupyter_path)
            return "https://colab.research.google.com/notebook#" + unescaped
        return None

    @computed_field
    @property
    def deploymenet(self) -> Literal["local", "cloud"]:
        return "local" if self.is_local else "cloud"

    @computed_field
    @property
    def is_local(self) -> bool:
        return self.base_url != "https://api.wandb.ai"

    @computed_field
    @property
    def project_url(self) -> AnyHttpUrl:
        project_url = self._project_url_base()
        if not project_url:
            return ""

        query = self._get_url_query_string()

        return f"{project_url}{query}"

    @computed_field
    @property
    def run_mode(self) -> Literal["run", "offline-run"]:
        return "run" if not self._offline else "offline-run"

    @computed_field
    @property
    def run_url(self) -> AnyHttpUrl:
        project_url = self._project_url_base()
        if not all([project_url, self.run_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/runs/{quote(self.run_id)}{query}"

    @computed_field
    @property
    def sweep_url(self) -> AnyHttpUrl:
        project_url = self._project_url_base()
        if not all([project_url, self.sweep_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/sweeps/{quote(self.sweep_id)}{query}"

    @computed_field
    @property
    def sync_dir(self) -> str:
        return self._path_convert(
            self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}"
        )

    @computed_field
    @property
    def sync_file(self) -> str:
        return self._path_convert(self.sync_dir, f"run-{self.run_id}.wandb")

    @computed_field
    @property
    def timespec(self) -> str:
        return self.start_datetime

    @computed_field
    @property
    def wandb_dir(self) -> str:
        return self._get_wandb_dir(self.root_dir or "")

    # TODO: Methods to collect settings from different sources.
    def from_env(self): ...

    # Helper methods.
    @staticmethod
    def _path_convert(*args: str) -> str:
        """Join path and apply os.path.expanduser to it."""
        return os.path.expanduser(os.path.join(*args))

    def _project_url_base(self) -> str:
        if not all([self.entity, self.project]):
            return ""

        app_url = util.app_url(self.base_url)
        return f"{app_url}/{quote(self.entity)}/{quote(self.project)}"

    def _get_url_query_string(self) -> str:
        # TODO: use `wandb_settings` (if self.anonymous != "true")
        if Api().settings().get("anonymous") != "true":
            return ""

        api_key = apikey.api_key(settings=self)

        return f"?{urlencode({'apiKey': api_key})}"

    @staticmethod
    def _get_program_relpath(program: str, root: str | None = None) -> str | None:
        if not program:
            return None

        root = root or os.getcwd()
        if not root:
            return None

        full_path_to_program = os.path.join(
            root, os.path.relpath(os.getcwd(), root), program
        )
        if os.path.exists(full_path_to_program):
            relative_path = os.path.relpath(full_path_to_program, start=root)
            if "../" in relative_path:
                return None
            return relative_path

        return None

    @staticmethod
    def _get_wandb_dir(root_dir: str) -> str:
        """Get the full path to the wandb directory.

        The setting exposed to users as `dir=` or `WANDB_DIR` is the `root_dir`.
        We add the `__stage_dir__` to it to get the full `wandb_dir`
        """
        # We use the hidden version if it already exists, otherwise non-hidden.
        if os.path.exists(os.path.join(root_dir, ".wandb")):
            __stage_dir__ = ".wandb" + os.sep
        else:
            __stage_dir__ = "wandb" + os.sep

        path = os.path.join(root_dir, __stage_dir__)
        if not os.access(root_dir or ".", os.W_OK):
            termwarn(
                f"Path {path} wasn't writable, using system temp directory.",
                repeat=False,
            )
            path = os.path.join(
                tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep)
            )

        return os.path.expanduser(path)
