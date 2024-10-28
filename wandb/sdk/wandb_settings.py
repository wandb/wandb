from __future__ import annotations

import datetime
import logging
import multiprocessing
import os
import platform
import sys
import tempfile
import time
from typing import Literal, Sequence
from urllib.parse import quote, unquote, urlencode

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from wandb import termwarn, util
from wandb.apis.internal import Api
from wandb.errors import UsageError

from .lib import apikey, credentials, ipython
from .lib.run_moment import RunMoment


class Settings(BaseModel, validate_assignment=True):
    """Settings for W&B."""

    allow_val_change: bool = False
    anonymous: Literal["allow", "must", "never", "false", "true"] | None = None
    api_key: str | None = None
    azure_account_url_to_access_key: dict[str, str] | None = None
    # The base URL for the W&B API.
    base_url: AnyHttpUrl = "https://api.wandb.ai"
    code_dir: str | None = None
    config_paths: Sequence[str] | None = None
    console: Literal["auto", "off", "wrap", "redirect", "wrap_raw", "wrap_emu"] = "auto"
    # whether to produce multipart console log files
    console_multipart: bool = False
    # file path to write access tokens
    credentials_file: str = str(credentials.DEFAULT_WANDB_CREDENTIALS_FILE)
    disable_code: bool = False
    disable_git: bool = False
    disable_job_creation: bool = False
    docker: str | None = None
    email: str | None = None
    entity: str | None = None
    force: bool = False
    fork_from: RunMoment | None = None
    git_commit: str | None = None
    git_remote: str = "origin"
    git_remote_url: str | None = None
    git_root: str | None = None
    heartbeat_seconds: int = 30
    host: str | None = None
    http_proxy: AnyHttpUrl | None = None
    https_proxy: AnyHttpUrl | None = None
    # file path to supply a jwt for authentication
    identity_token_file: str | None = None
    ignore_globs: tuple[str] = ()
    init_timeout: float = 90.0
    job_name: str | None = None
    job_source: Literal["repo", "artifact", "image"] | None = None
    label_disable: bool = False
    launch: bool = False
    launch_config_path: str | None = None
    login_timeout: float | None = None
    mode: Literal["online", "offline", "dryrun", "disabled", "run", "shared"] = "online"
    notebook_name: str | None = None
    program: str | None = None
    program_abspath: str | None = None
    program_relpath: str | None = None
    project: str | None = None
    quiet: bool = False
    reinit: bool = False
    relogin: bool = False
    resume: Literal["allow", "must", "never", "auto"] | None = None
    resume_from: RunMoment | None = None
    # Indication from the server about the state of the run.
    # NOTE: this is different from resume, a user provided flag
    resumed: bool = False
    root_dir: str = os.path.abspath(os.getcwd())
    run_group: str | None = None
    run_id: str | None = None
    run_job_type: str | None = None
    run_name: str | None = None
    run_notes: str | None = None
    run_tags: tuple[str] | None = None
    sagemaker_disable: bool = False
    save_code: bool | None = None
    settings_system: str = os.path.join("~", ".config", "wandb", "settings")
    show_colors: bool | None = None
    show_emoji: bool | None = None
    show_errors: bool = True
    show_info: bool = True
    show_warnings: bool = True
    silent: bool = False
    start_method: str | None = None
    strict: bool | None = None
    summary_timeout: int = 60
    summary_warnings: int = 5  # TODO: kill this with fire
    sweep_id: str | None = None
    sweep_param_path: str | None = None
    symlink: bool = False if platform.system() == "Windows" else True
    table_raise_on_max_row_limit_exceeded: bool = False
    username: str | None = None

    # Internal settings.
    #
    # These are typically not meant to be set by the user and should not be considered
    # a part of the public API as they may change or be removed in future versions.

    # CLI mode.
    x_cli_only_mode: bool = False
    # Do not collect system metadata
    x_disable_meta: bool = False
    # Do not collect system metrics
    x_disable_service: bool = False
    # Do not use setproctitle on internal process
    x_disable_setproctitle: bool = False
    # Do not collect system metrics
    x_disable_stats: bool = False
    # Disable version check
    x_disable_update_check: bool = False
    # Prevent early viewer query
    x_disable_viewer: bool = False
    # Disable automatic machine info collection
    x_disable_machine_info: bool = False
    x_extra_http_headers: dict[str, str] | None = None
    # max size for filestream requests in core
    x_file_stream_max_bytes: int | None = None
    # tx interval for filestream requests in core
    x_file_stream_transmit_interval: float | None = None
    # file stream retry client configuration
    # max number of retries
    x_file_stream_retry_max: int | None = None
    # min wait time between retries
    x_file_stream_retry_wait_min_seconds: float | None = None
    # max wait time between retries
    x_file_stream_retry_wait_max_seconds: float | None = None
    # timeout for individual HTTP requests
    x_file_stream_timeout_seconds: float | None = None
    # file transfer retry client configuration
    x_file_transfer_retry_max: int | None = None
    x_file_transfer_retry_wait_min_seconds: float | None = None
    x_file_transfer_retry_wait_max_seconds: float | None = None
    x_file_transfer_timeout_seconds: float | None = None
    # graphql retry client configuration
    x_graphql_retry_max: int | None = None
    x_graphql_retry_wait_min_seconds: float | None = None
    x_graphql_retry_wait_max_seconds: float | None = None
    x_graphql_timeout_seconds: float | None = None
    x_internal_check_process: float = 8.0
    x_internal_queue_timeout: float = 2.0
    x_jupyter_name: str | None = None
    x_jupyter_path: str | None = None
    x_jupyter_root: str | None = None
    x_live_policy_rate_limit: int | None = None
    x_live_policy_wait_time: int | None = None
    x_log_level: int = logging.INFO
    x_network_buffer: int | None = None
    # [deprecated, use http(s)_proxy] custom proxy servers for the requests to W&B
    # [scheme -> url].
    x_proxies: dict[str, str] | None = None
    x_runqueue_item_id: str | None = None
    x_require_legacy_service: bool = False
    x_save_requirements: bool = False
    x_service_transport: str | None = None
    x_service_wait: float = Field(default=30.0, internal=True)
    x_show_operation_stats: bool = False
    x_start_time: float = time.time()
    # PID of the process that started the wandb-core process to collect system stats for.
    x_stats_pid: int = os.getpid()
    # Sampling interval for the system monitor.
    x_stats_sampling_interval: float = Field(default=10.0)
    # Path to store the default config file for neuron-monitor tool
    # used to monitor AWS Trainium devices.
    x_stats_neuron_monitor_config_path: str | None = None
    # open metrics endpoint names/urls
    x_stats_open_metrics_endpoints: dict[str, str] | None = None
    # open metrics filters in one of the two formats:
    # - {"metric regex pattern, including endpoint name as prefix": {"label": "label value regex pattern"}}
    # - ("metric regex pattern 1", "metric regex pattern 2", ...)
    x_stats_open_metrics_filters: dict[str, dict[str, str]] | Sequence[str] | None = (
        None
    )
    # paths to monitor disk usage
    x_stats_disk_paths: Sequence[str] | None = None
    # number of system metric samples to buffer in memory in wandb-core before purging.
    # can be accessed via wandb._system_metrics
    x_stats_buffer_size: int = 0
    x_sync: bool = False
    x_tracelog: str | None = None

    # Model validator to catch legacy settings.
    @model_validator(mode="before")
    @classmethod
    def catch_private_settings(cls, values):
        """Check if a private field is provided and assign to the corrsponding public one.

        This is a compatibility layer to handle previous versions of the settings.
        """
        new_values = {}
        for key in values:
            # Internal settings are prefixed with "x_" instead of "_"
            # as Pydantic does not allow "_" in field names.
            if key.startswith("_"):
                new_values["x" + key] = values[key]
            else:
                new_values[key] = values[key]
        return new_values

    # Field validators.
    @field_validator("x_disable_service", mode="before")
    @classmethod
    def validate_disable_service(cls, value):
        if value:
            termwarn(
                "Disabling the wandb service is deprecated as of version 0.18.0 "
                "and will be removed in future versions. ",
                repeat=False,
            )
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value):
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
            ipython.in_jupyter()
            or (info.data.get("start_method") == "thread")
            or not info.data.get("disable_service")
            or platform.system() == "Windows"
        ):
            value = "wrap"
        else:
            value = "redirect"
        return value

    @field_validator("x_disable_meta", mode="after")
    @classmethod
    def validate_disable_meta(cls, value, info):
        if info.data.get("x_disable_machine_info"):
            return True
        return value

    @field_validator("x_disable_stats", mode="after")
    @classmethod
    def validate_disable_stats(cls, value, info):
        if info.data.get("x_disable_machine_info"):
            return True
        return value

    @field_validator("disable_code", mode="after")
    @classmethod
    def validate_disable_code(cls, value, info):
        if info.data.get("x_disable_machine_info"):
            return True
        return value

    @field_validator("disable_git", mode="after")
    @classmethod
    def validate_disable_git(cls, value, info):
        if info.data.get("x_disable_machine_info"):
            return True
        return value

    @field_validator("disable_job_creation", mode="after")
    @classmethod
    def validate_disable_job_creation(cls, value, info):
        if info.data.get("x_disable_machine_info"):
            return True
        return value

    @field_validator("fork_from", mode="before")
    @classmethod
    def validate_fork_from(cls, value) -> RunMoment | None:
        return cls._runmoment_preprocessor(value)

    @field_validator("ignore_globs", mode="before")
    @classmethod
    def validate_ignore_globs(cls, value):
        return tuple(value) if not isinstance(value, tuple) else value

    @field_validator("program", mode="after")
    @classmethod
    def validate_program(cls, program, info):
        if program is not None and program != "<python with no main file>":
            return program

        if not ipython.in_jupyter():
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

    @field_validator("resume", mode="before")
    @classmethod
    def validate_resume(cls, value):
        if value is False:
            return None
        if value is True:
            return "auto"
        return value

    @field_validator("resume_from", mode="before")
    @classmethod
    def validate_resume_from(cls, value) -> RunMoment | None:
        return cls._runmoment_preprocessor(value)

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

    @field_validator("settings_system", mode="after")
    @classmethod
    def validate_settings_system(cls, value):
        return cls._path_convert(value)

    @field_validator("x_service_wait", mode="before")
    @classmethod
    def validate_service_wait(cls, value):
        if value < 0:
            raise UsageError("Service wait time cannot be negative")
        return

    @field_validator("start_method")
    @classmethod
    def validate_start_method(cls, value):
        available_methods = ["thread"]
        if hasattr(multiprocessing, "get_all_start_methods"):
            available_methods += multiprocessing.get_all_start_methods()
        if value not in available_methods:
            raise UsageError(
                f"Settings field `start_method`: {value!r} not in {available_methods}"
            )
        return value

    @field_validator("x_stats_sampling_interval", mode="before")
    @classmethod
    def validate_stats_sampling_interval(cls, value):
        if value < 0.1:
            raise UsageError("Stats sampling interval cannot be less than 0.1 seconds")
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
    # TODO: remove underscores from underscored fields.
    @computed_field
    @property
    def _args(self) -> list[str]:
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
        if not self.program:
            return None

        root = os.getcwd()
        if not root:
            return None

        full_path_to_program = os.path.join(
            root, os.path.relpath(os.getcwd(), root), self.program
        )
        if os.path.exists(full_path_to_program):
            relative_path = os.path.relpath(full_path_to_program, start=root)
            if "../" in relative_path:
                return None
            return relative_path

        return None

    @computed_field
    @property
    def _colab(self) -> bool:
        return "google.colab" in sys.modules

    @computed_field
    @property
    def _ipython(self) -> bool:
        return ipython.in_ipython()

    @computed_field
    @property
    def _jupyter(self) -> bool:
        return ipython.in_jupyter()

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
    def _start_datetime(self) -> str:
        datetime_now = datetime.datetime.fromtimestamp(self.x_start_time)
        return datetime_now.strftime("%Y%m%d_%H%M%S")

    @computed_field
    @property
    def _tmp_code_dir(self) -> str:
        return self._path_convert(self.wandb_dir, "tmp", "code")

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
    def deployment(self) -> Literal["local", "cloud"]:
        return "local" if self.is_local else "cloud"

    @computed_field
    @property
    def files_dir(self) -> str:
        return self._path_convert(
            self.wandb_dir,
            f"{self.run_mode}-{self.timespec}-{self.run_id}",
            "files",
        )

    @computed_field
    @property
    def is_local(self) -> bool:
        return self.base_url != "https://api.wandb.ai"

    @computed_field
    @property
    def log_dir(self) -> str:
        return self._path_convert(
            self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", "logs"
        )

    @computed_field
    @property
    def log_internal(self) -> str:
        return self._path_convert(self.log_dir, "debug-internal.log")

    @computed_field
    @property
    def log_symlink_internal(self) -> str:
        return self._path_convert(self.wandb_dir, "debug-internal.log")

    @computed_field
    @property
    def log_symlink_user(self) -> str:
        return self._path_convert(self.wandb_dir, "debug.log")

    @computed_field
    @property
    def log_user(self) -> str:
        return self._path_convert(self.log_dir, "debug.log")

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
    def settings_workspace(self) -> str:
        return self._path_convert(self.wandb_dir, "settings")

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
    def sync_symlink_latest(self) -> str:
        return self._path_convert(self.wandb_dir, "latest-run")

    @computed_field
    @property
    def timespec(self) -> str:
        return self._start_datetime

    @computed_field
    @property
    def wandb_dir(self) -> str:
        """Full path to the wandb directory.

        The setting exposed to users as `dir=` or `WANDB_DIR` is the `root_dir`.
        We add the `__stage_dir__` to it to get the full `wandb_dir`
        """
        root_dir = self.root_dir or ""

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
    def _runmoment_preprocessor(val: RunMoment | str | None) -> RunMoment | None:
        if isinstance(val, RunMoment) or val is None:
            return val
        elif isinstance(val, str):
            return RunMoment.from_uri(val)
