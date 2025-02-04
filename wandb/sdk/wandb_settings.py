from __future__ import annotations

import configparser
import json
import logging
import multiprocessing
import os
import pathlib
import platform
import re
import shutil
import socket
import sys
import tempfile
from datetime import datetime
from typing import Any, Literal, Sequence
from urllib.parse import quote, unquote, urlencode

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from google.protobuf.wrappers_pb2 import BoolValue, DoubleValue, Int32Value, StringValue
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import SchemaValidator, core_schema

import wandb
from wandb import env, termwarn, util
from wandb.errors import UsageError
from wandb.proto import wandb_settings_pb2

from .lib import apikey, credentials, ipython
from .lib.gitlib import GitRepo
from .lib.run_moment import RunMoment


def _path_convert(*args: str) -> str:
    """Join path and apply os.path.expanduser to it."""
    return os.path.expanduser(os.path.join(*args))


class Settings(BaseModel, validate_assignment=True):
    """Settings for the W&B SDK.

    This class manages configuration settings for the W&B SDK,
    ensuring type safety and validation of all settings. Settings are accessible
    as attributes and can be initialized programmatically, through environment
    variables (WANDB_ prefix), and via configuration files.

    The settings are organized into three categories:
    1. Public settings: Core configuration options that users can safely modify to customize
       W&B's behavior for their specific needs.
    2. Internal settings: Settings prefixed with 'x_' that handle low-level SDK behavior.
       These settings are primarily for internal use and debugging. While they can be modified,
       they are not considered part of the public API and may change without notice in future
       versions.
    3. Computed settings: Read-only settings that are automatically derived from other settings or
       the environment.
    """

    # Pydantic Model configuration.
    model_config = ConfigDict(
        extra="forbid",  # throw an error if extra fields are provided
        validate_default=True,  # validate default values
        use_attribute_docstrings=True,  # for field descriptions
        revalidate_instances="always",
    )

    # Public settings.

    allow_offline_artifacts: bool = True
    """Flag to allow table artifacts to be synced in offline mode.

    To revert to the old behavior, set this to False.
    """

    allow_val_change: bool = False
    """Flag to allow modification of `Config` values after they've been set."""

    anonymous: Literal["allow", "must", "never"] | None = None
    """Controls anonymous data logging.

    Possible values are:
    - "never": requires you to link your W&B account before
       tracking the run, so you don't accidentally create an anonymous
       run.
    - "allow": lets a logged-in user track runs with their account, but
       lets someone who is running the script without a W&B account see
       the charts in the UI.
    - "must": sends the run to an anonymous account instead of to a
       signed-up user account.
    """

    api_key: str | None = None
    """The W&B API key."""

    azure_account_url_to_access_key: dict[str, str] | None = None
    """Mapping of Azure account URLs to their corresponding access keys for Azure integration."""

    base_url: str = "https://api.wandb.ai"
    """The URL of the W&B backend for data synchronization."""

    code_dir: str | None = None
    """Directory containing the code to be tracked by W&B."""

    config_paths: Sequence[str] | None = None
    """Paths to files to load configuration from into the `Config` object."""

    console: Literal["auto", "off", "wrap", "redirect", "wrap_raw", "wrap_emu"] = Field(
        default="auto",
        validate_default=True,
    )
    """The type of console capture to be applied.

    Possible values are:
     "auto" - Automatically selects the console capture method based on the
      system environment and settings.

      "off" - Disables console capture.

      "redirect" - Redirects low-level file descriptors for capturing output.

      "wrap" - Overrides the write methods of sys.stdout/sys.stderr. Will be
      mapped to either "wrap_raw" or "wrap_emu" based on the state of the system.

      "wrap_raw" - Same as "wrap" but captures raw output directly instead of
      through an emulator. Derived from the `wrap` setting and should not be set manually.

      "wrap_emu" - Same as "wrap" but captures output through an emulator.
      Derived from the `wrap` setting and should not be set manually.
      """

    console_multipart: bool = False
    """Whether to produce multipart console log files."""

    credentials_file: str = Field(
        default_factory=lambda: str(credentials.DEFAULT_WANDB_CREDENTIALS_FILE)
    )
    """Path to file for writing temporary access tokens."""

    disable_code: bool = False
    """Whether to disable capturing the code."""

    disable_git: bool = False
    """Whether to disable capturing the git state."""

    disable_job_creation: bool = True
    """Whether to disable the creation of a job artifact for W&B Launch."""

    docker: str | None = None
    """The Docker image used to execute the script."""

    email: str | None = None
    """The email address of the user."""

    entity: str | None = None
    """The W&B entity, such as a user or a team."""

    force: bool = False
    """Whether to pass the `force` flag to `wandb.login()`."""

    fork_from: RunMoment | None = None
    """Specifies a point in a previous execution of a run to fork from.

    The point is defined by the run ID, a metric, and its value.
    Currently, only the metric '_step' is supported.
    """

    git_commit: str | None = None
    """The git commit hash to associate with the run."""

    git_remote: str = "origin"
    """The git remote to associate with the run."""

    git_remote_url: str | None = None
    """The URL of the git remote repository."""

    git_root: str | None = None
    """Root directory of the git repository."""

    heartbeat_seconds: int = 30
    """Interval in seconds between heartbeat signals sent to the W&B servers."""

    host: str | None = None
    """Hostname of the machine running the script."""

    http_proxy: str | None = None
    """Custom proxy servers for http requests to W&B."""

    https_proxy: str | None = None
    """Custom proxy servers for https requests to W&B."""

    # Path to file containing an identity token (JWT) for authentication.
    identity_token_file: str | None = None
    """Path to file containing an identity token (JWT) for authentication."""

    ignore_globs: tuple[str, ...] = ()
    """Unix glob patterns relative to `files_dir` specifying files to exclude from upload."""

    init_timeout: float = 90.0
    """Time in seconds to wait for the `wandb.init` call to complete before timing out."""

    insecure_disable_ssl: bool = False
    """Whether to insecurely disable SSL verification."""

    job_name: str | None = None
    """Name of the Launch job running the script."""

    job_source: Literal["repo", "artifact", "image"] | None = None
    """Source type for Launch."""

    label_disable: bool = False
    """Whether to disable automatic labeling features."""

    launch: bool = False
    """Flag to indicate if the run is being launched through W&B Launch."""

    launch_config_path: str | None = None
    """Path to the launch configuration file."""

    login_timeout: float | None = None
    """Time in seconds to wait for login operations before timing out."""

    mode: Literal["online", "offline", "dryrun", "disabled", "run", "shared"] = Field(
        default="online",
        validate_default=True,
    )
    """The operating mode for W&B logging and synchronization."""

    notebook_name: str | None = None
    """Name of the notebook if running in a Jupyter-like environment."""

    program: str | None = None
    """Path to the script that created the run, if available."""

    program_abspath: str | None = None
    """The absolute path from the root repository directory to the script that
    created the run.

    Root repository directory is defined as the directory containing the
    .git directory, if it exists. Otherwise, it's the current working directory.
    """

    program_relpath: str | None = None
    """The relative path to the script that created the run."""

    project: str | None = None
    """The W&B project ID."""

    quiet: bool = False
    """Flag to suppress non-essential output."""

    reinit: bool = False
    """Flag to allow reinitialization of a run.

    If not set, when an active run exists, calling `wandb.init()` returns the existing run
    instead of creating a new one.
    """

    relogin: bool = False
    """Flag to force a new login attempt."""

    resume: Literal["allow", "must", "never", "auto"] | None = None
    """Specifies the resume behavior for the run.

    The available options are:

      "must": Resumes from an existing run with the same ID. If no such run exists,
      it will result in failure.

      "allow": Attempts to resume from an existing run with the same ID. If none is
      found, a new run will be created.

      "never": Always starts a new run. If a run with the same ID already exists,
      it will result in failure.

      "auto": Automatically resumes from the most recent failed run on the same
      machine.
    """

    resume_from: RunMoment | None = None
    """Specifies a point in a previous execution of a run to resume from.

    The point is defined by the run ID, a metric, and its value.
    Currently, only the metric '_step' is supported.
    """

    resumed: bool = False
    """Indication from the server about the state of the run.

    This is different from resume, a user provided flag.
    """

    root_dir: str = Field(default_factory=lambda: os.path.abspath(os.getcwd()))
    """The root directory to use as the base for all run-related paths.

    In particular, this is used to derive the wandb directory and the run directory.
    """

    run_group: str | None = None
    """Group identifier for related runs.

    Used for grouping runs in the UI.
    """

    run_id: str | None = None
    """The ID of the run."""

    run_job_type: str | None = None
    """Type of job being run (e.g., training, evaluation)."""

    run_name: str | None = None
    """Human-readable name for the run."""

    run_notes: str | None = None
    """Additional notes or description for the run."""

    run_tags: tuple[str, ...] | None = None
    """Tags to associate with the run for organization and filtering."""

    sagemaker_disable: bool = False
    """Flag to disable SageMaker-specific functionality."""

    save_code: bool | None = None
    """Whether to save the code associated with the run."""

    settings_system: str = Field(
        default_factory=lambda: _path_convert(
            os.path.join("~", ".config", "wandb", "settings")
        )
    )
    """Path to the system-wide settings file."""

    show_colors: bool | None = None
    """Whether to use colored output in the console."""

    show_emoji: bool | None = None
    """Whether to show emoji in the console output."""

    show_errors: bool = True
    """Whether to display error messages."""

    show_info: bool = True
    """Whether to display informational messages."""

    show_warnings: bool = True
    """Whether to display warning messages."""

    silent: bool = False
    """Flag to suppress all output."""

    start_method: str | None = None
    """Method to use for starting subprocesses."""

    strict: bool | None = None
    """Whether to enable strict mode for validation and error checking."""

    summary_timeout: int = 60
    """Time in seconds to wait for summary operations before timing out."""

    summary_warnings: int = 5  # TODO: kill this with fire
    """Maximum number of summary warnings to display."""

    sweep_id: str | None = None
    """Identifier of the sweep this run belongs to."""

    sweep_param_path: str | None = None
    """Path to the sweep parameters configuration."""

    symlink: bool = Field(
        default_factory=lambda: False if platform.system() == "Windows" else True
    )
    """Whether to use symlinks (True by default except on Windows)."""

    sync_tensorboard: bool | None = None
    """Whether to synchronize TensorBoard logs with W&B."""

    table_raise_on_max_row_limit_exceeded: bool = False
    """Whether to raise an exception when table row limits are exceeded."""

    username: str | None = None
    """Username."""

    # Internal settings.
    #
    # These are typically not meant to be set by the user and should not be considered
    # a part of the public API as they may change or be removed in future versions.

    x_cli_only_mode: bool = False
    """Flag to indicate that the SDK is running in CLI-only mode."""

    x_disable_meta: bool = False
    """Flag to disable the collection of system metadata."""

    x_disable_service: bool = False
    """Flag to disable the W&B service.

    This is deprecated and will be removed in future versions."""

    x_disable_setproctitle: bool = False
    """Flag to disable using setproctitle for the internal process in the legacy service.

    This is deprecated and will be removed in future versions.
    """

    x_disable_stats: bool = False
    """Flag to disable the collection of system metrics."""

    x_disable_viewer: bool = False
    """Flag to disable the early viewer query."""

    x_disable_machine_info: bool = False
    """Flag to disable automatic machine info collection."""

    x_executable: str | None = None
    """Path to the Python executable."""

    x_extra_http_headers: dict[str, str] | None = None
    """Additional headers to add to all outgoing HTTP requests."""

    x_file_stream_max_bytes: int | None = None
    """An approximate maximum request size for the filestream API.

    Its purpose is to prevent HTTP requests from failing due to
    containing too much data. This number is approximate:
    requests will be slightly larger.
    """

    x_file_stream_max_line_bytes: int | None = None
    """Maximum line length for filestream JSONL files."""

    x_file_stream_transmit_interval: float | None = None
    """Interval in seconds between filestream transmissions."""

    # Filestream retry client configuration.

    x_file_stream_retry_max: int | None = None
    """Max number of retries for filestream operations."""

    x_file_stream_retry_wait_min_seconds: float | None = None
    """Minimum wait time between retries for filestream operations."""

    x_file_stream_retry_wait_max_seconds: float | None = None
    """Maximum wait time between retries for filestream operations."""

    x_file_stream_timeout_seconds: float | None = None
    """Timeout in seconds for individual filestream HTTP requests."""

    # file transfer retry client configuration

    x_file_transfer_retry_max: int | None = None
    """Max number of retries for file transfer operations."""

    x_file_transfer_retry_wait_min_seconds: float | None = None
    """Minimum wait time between retries for file transfer operations."""

    x_file_transfer_retry_wait_max_seconds: float | None = None
    """Maximum wait time between retries for file transfer operations."""

    x_file_transfer_timeout_seconds: float | None = None
    """Timeout in seconds for individual file transfer HTTP requests."""

    x_files_dir: str | None = None
    """Override setting for the computed files_dir.."""

    x_flow_control_custom: bool | None = None
    """Flag indicating custom flow control for filestream.

    TODO: Not implemented in wandb-core.
    """

    x_flow_control_disabled: bool | None = None
    """Flag indicating flow control is disabled for filestream.

    TODO: Not implemented in wandb-core.
    """

    # graphql retry client configuration

    x_graphql_retry_max: int | None = None
    """Max number of retries for GraphQL operations."""

    x_graphql_retry_wait_min_seconds: float | None = None
    """Minimum wait time between retries for GraphQL operations."""

    x_graphql_retry_wait_max_seconds: float | None = None
    """Maximum wait time between retries for GraphQL operations."""

    x_graphql_timeout_seconds: float | None = None
    """Timeout in seconds for individual GraphQL requests."""

    x_internal_check_process: float = 8.0
    """Interval for internal process health checks in seconds."""

    x_jupyter_name: str | None = None
    """Name of the Jupyter notebook."""

    x_jupyter_path: str | None = None
    """Path to the Jupyter notebook."""

    x_jupyter_root: str | None = None
    """Root directory of the Jupyter notebook."""

    x_label: str | None = None
    """Label to assign to system metrics and console logs collected for the run.

    This is used to group data by on the frontend and can be used to distinguish data
    from different processes in a distributed training job.
    """

    x_live_policy_rate_limit: int | None = None
    """Rate limit for live policy updates in seconds."""

    x_live_policy_wait_time: int | None = None
    """Wait time between live policy updates in seconds."""

    x_log_level: int = logging.INFO
    """Logging level for internal operations."""

    x_network_buffer: int | None = None
    """Size of the network buffer used in flow control.

    TODO: Not implemented in wandb-core.
    """

    x_primary: bool = Field(
        default=True, validation_alias=AliasChoices("x_primary", "x_primary_node")
    )
    """Determines whether to save internal wandb files and metadata.

    In a distributed setting, this is useful for avoiding file overwrites
    from secondary processes when only system metrics and logs are needed,
    as the primary process handles the main logging.
    """

    x_proxies: dict[str, str] | None = None
    """Custom proxy servers for requests to W&B.

    This is deprecated and will be removed in future versions.
    Please use `http_proxy` and `https_proxy` instead.
    """

    x_runqueue_item_id: str | None = None
    """ID of the Launch run queue item being processed."""

    x_require_legacy_service: bool = False
    """Force the use of legacy wandb service."""

    x_save_requirements: bool = True
    """Flag to save the requirements file."""

    x_service_transport: str | None = None
    """Transport method for communication with the wandb service."""

    x_service_wait: float = 30.0
    """Time in seconds to wait for the wandb-core internal service to start."""

    x_show_operation_stats: bool = True
    """Whether to show statistics about internal operations such as data uploads."""

    x_start_time: float | None = None
    """The start time of the run in seconds since the Unix epoch."""

    x_stats_pid: int = os.getpid()
    """PID of the process that started the wandb-core process to collect system stats for."""

    x_stats_sampling_interval: float = Field(default=10.0)
    """Sampling interval for the system monitor in seconds."""

    x_stats_neuron_monitor_config_path: str | None = None
    """Path to the default config file for the neuron-monitor tool.

    This is used to monitor AWS Trainium devices.
    """

    x_stats_dcgm_exporter: str | None = None
    """Endpoint to extract Nvidia DCGM metrics from.

    Two options are supported:
    - Extract DCGM-related metrics from a query to the Prometheus `/api/v1/query` endpoint.
      It is a common practice to aggregate metrics reported by the instances of the DCGM Exporter
      running on different nodes in a cluster using Prometheus.
    - TODO: Parse metrics directly from the `/metrics` endpoint of the DCGM Exporter.

    Examples:
    - `http://localhost:9400/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP{node="l1337", cluster="globular"}`.
    - TODO: `http://192.168.0.1:9400/metrics`.
    """

    x_stats_open_metrics_endpoints: dict[str, str] | None = None
    """OpenMetrics `/metrics` endpoints to monitor for system metrics."""

    x_stats_open_metrics_filters: dict[str, dict[str, str]] | Sequence[str] | None = (
        None
    )
    """Filter to apply to metrics collected from OpenMetrics `/metrics` endpoints.

    Supports two formats:
    - {"metric regex pattern, including endpoint name as prefix": {"label": "label value regex pattern"}}
    - ("metric regex pattern 1", "metric regex pattern 2", ...)
    """

    x_stats_open_metrics_http_headers: dict[str, str] | None = None
    """HTTP headers to add to OpenMetrics requests."""

    x_stats_disk_paths: Sequence[str] | None = Field(
        default_factory=lambda: ("/", "/System/Volumes/Data")
        if platform.system() == "Darwin"
        else ("/",)
    )
    """System paths to monitor for disk usage."""

    x_stats_gpu_device_ids: Sequence[int] | None = None
    """GPU device indices to monitor.

    If not set, captures metrics for all GPUs.
    Assumes 0-based indexing matching CUDA/ROCm device enumeration.
    """

    x_stats_buffer_size: int = 0
    """Number of system metric samples to buffer in memory in the wandb-core process.

    Can be accessed via run._system_metrics.
    """

    x_sync: bool = False
    """Flag to indicate whether we are syncing a run from the transaction log."""

    x_update_finish_state: bool = True
    """Flag to indicate whether this process can update the run's final state on the server.

    Set to False in distributed training when only the main process should determine the final state.
    """

    # Model validator to catch legacy settings.
    @model_validator(mode="before")
    @classmethod
    def catch_private_settings(cls, values):
        """Check if a private field is provided and assign to the corresponding public one.

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

    @model_validator(mode="after")
    def validate_mutual_exclusion_of_branching_args(self) -> Self:
        if (
            sum(
                o is not None
                for o in [
                    self.fork_from,
                    self.resume,
                    self.resume_from,
                ]
            )
            > 1
        ):
            raise ValueError(
                "`fork_from`, `resume`, or `resume_from` are mutually exclusive. "
                "Please specify only one of them."
            )
        return self

    # Field validators.

    @field_validator("x_disable_service", mode="after")
    @classmethod
    def validate_disable_service(cls, value):
        if value:
            termwarn(
                "Disabling the wandb service is deprecated as of version 0.18.0 "
                "and will be removed in future versions. ",
                repeat=False,
            )
        return value

    @field_validator("api_key", mode="after")
    @classmethod
    def validate_api_key(cls, value):
        if value is not None and (len(value) > len(value.strip())):
            raise UsageError("API key cannot start or end with whitespace")
        return value

    @field_validator("base_url", mode="after")
    @classmethod
    def validate_base_url(cls, value):
        cls.validate_url(value)
        # wandb.ai-specific checks
        if re.match(r".*wandb\.ai[^\.]*$", value) and "api." not in value:
            # user might guess app.wandb.ai or wandb.ai is the default cloud server
            raise ValueError(
                f"{value} is not a valid server address, did you mean https://api.wandb.ai?"
            )
        elif re.match(r".*wandb\.ai[^\.]*$", value) and not value.startswith("https"):
            raise ValueError("http is not secure, please use https://api.wandb.ai")
        return value.rstrip("/")

    @field_validator("code_dir", mode="before")
    @classmethod
    def validate_code_dir(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

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

    @field_validator("x_executable", mode="before")
    @classmethod
    def validate_x_executable(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("x_file_stream_max_line_bytes", mode="after")
    @classmethod
    def validate_file_stream_max_line_bytes(cls, value):
        if value is not None and value < 1:
            raise ValueError("File stream max line bytes must be greater than 0")
        return value

    @field_validator("x_files_dir", mode="before")
    @classmethod
    def validate_x_files_dir(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("fork_from", mode="before")
    @classmethod
    def validate_fork_from(cls, value, info) -> RunMoment | None:
        run_moment = cls._runmoment_preprocessor(value)
        if (
            run_moment
            and info.data.get("run_id") is not None
            and info.data.get("run_id") == run_moment.run
        ):
            raise ValueError(
                "Provided `run_id` is the same as the run to `fork_from`. "
                "Please provide a different `run_id` or remove the `run_id` argument. "
                "If you want to rewind the current run, please use `resume_from` instead."
            )
        return run_moment

    @field_validator("http_proxy", mode="after")
    @classmethod
    def validate_http_proxy(cls, value):
        if value is None:
            return None
        cls.validate_url(value)
        return value.rstrip("/")

    @field_validator("https_proxy", mode="after")
    @classmethod
    def validate_https_proxy(cls, value):
        if value is None:
            return None
        cls.validate_url(value)
        return value.rstrip("/")

    @field_validator("ignore_globs", mode="after")
    @classmethod
    def validate_ignore_globs(cls, value):
        return tuple(value) if not isinstance(value, tuple) else value

    @field_validator("program", mode="before")
    @classmethod
    def validate_program(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("program_abspath", mode="before")
    @classmethod
    def validate_program_abspath(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("program_relpath", mode="before")
    @classmethod
    def validate_program_relpath(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("project", mode="after")
    @classmethod
    def validate_project(cls, value, info):
        if value is None:
            return None
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
    def validate_resume_from(cls, value, info) -> RunMoment | None:
        run_moment = cls._runmoment_preprocessor(value)
        if (
            run_moment
            and info.data.get("run_id") is not None
            and info.data.get("run_id") != run_moment.run
        ):
            raise ValueError(
                "Both `run_id` and `resume_from` have been specified with different ids."
            )
        return run_moment

    @field_validator("root_dir", mode="before")
    @classmethod
    def validate_root_dir(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("run_id", mode="after")
    @classmethod
    def validate_run_id(cls, value, info):
        if value is None:
            return None

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
        if isinstance(value, pathlib.Path):
            return str(_path_convert(value))
        return _path_convert(value)

    @field_validator("x_service_wait", mode="after")
    @classmethod
    def validate_service_wait(cls, value):
        if value < 0:
            raise UsageError("Service wait time cannot be negative")
        return value

    @field_validator("start_method")
    @classmethod
    def validate_start_method(cls, value):
        if value is None:
            return value
        available_methods = ["thread"]
        if hasattr(multiprocessing, "get_all_start_methods"):
            available_methods += multiprocessing.get_all_start_methods()
        if value not in available_methods:
            raise UsageError(
                f"Settings field `start_method`: {value!r} not in {available_methods}"
            )
        return value

    @field_validator("x_stats_gpu_device_ids", mode="before")
    @classmethod
    def validate_x_stats_gpu_device_ids(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("x_stats_neuron_monitor_config_path", mode="before")
    @classmethod
    def validate_x_stats_neuron_monitor_config_path(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    @field_validator("x_stats_open_metrics_endpoints", mode="before")
    @classmethod
    def validate_stats_open_metrics_endpoints(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("x_stats_open_metrics_filters", mode="before")
    @classmethod
    def validate_stats_open_metrics_filters(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("x_stats_open_metrics_http_headers", mode="before")
    @classmethod
    def validate_stats_open_metrics_http_headers(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_validator("x_stats_sampling_interval", mode="after")
    @classmethod
    def validate_stats_sampling_interval(cls, value):
        if value < 0.1:
            raise UsageError("Stats sampling interval cannot be less than 0.1 seconds")
        return value

    @field_validator("sweep_id", mode="after")
    @classmethod
    def validate_sweep_id(cls, value):
        if value is None:
            return None
        if len(value) == 0:
            raise UsageError("Sweep ID cannot be empty")
        if len(value) > len(value.strip()):
            raise UsageError("Sweep ID cannot start or end with whitespace")
        if not bool(value.strip()):
            raise UsageError("Sweep ID cannot contain only whitespace")
        return value

    @field_validator("sweep_param_path", mode="before")
    @classmethod
    def validate_sweep_param_path(cls, value):
        # TODO: add native support for pathlib.Path
        if isinstance(value, pathlib.Path):
            return str(value)
        return value

    # Computed fields.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _args(self) -> list[str]:
        if not self._jupyter:
            return sys.argv[1:]
        return []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _aws_lambda(self) -> bool:
        """Check if we are running in a lambda environment."""
        from sentry_sdk.integrations.aws_lambda import (  # type: ignore[import-not-found]
            get_lambda_bootstrap,
        )

        lambda_bootstrap = get_lambda_bootstrap()
        if not lambda_bootstrap or not hasattr(
            lambda_bootstrap, "handle_event_request"
        ):
            return False
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _code_path_local(self) -> str | None:
        """The relative path from the current working directory to the code path.

        For example, if the code path is /home/user/project/example.py, and the
        current working directory is /home/user/project, then the code path local
        is example.py.

        If couldn't find the relative path, this will be an empty string.
        """
        return self._get_program_relpath(self.program) if self.program else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _colab(self) -> bool:
        return "google.colab" in sys.modules

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _ipython(self) -> bool:
        return ipython.in_ipython()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _jupyter(self) -> bool:
        return ipython.in_jupyter()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _kaggle(self) -> bool:
        return util._is_likely_kaggle()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _notebook(self) -> bool:
        return self._ipython or self._jupyter or self._colab or self._kaggle

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _offline(self) -> bool:
        return self.mode in ("offline", "dryrun")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _os(self) -> str:
        """The operating system of the machine running the script."""
        return platform.platform(aliased=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _platform(self) -> str:
        return f"{platform.system()}-{platform.machine()}".lower()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _python(self) -> str:
        return f"{platform.python_implementation()} {platform.python_version()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _shared(self) -> bool:
        """Whether we are in shared mode.

        In "shared" mode, multiple processes can write to the same run,
        for example from different machines.
        """
        return self.mode == "shared"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _start_datetime(self) -> str:
        if self.x_start_time is None:
            return ""
        datetime_now = datetime.fromtimestamp(self.x_start_time)
        return datetime_now.strftime("%Y%m%d_%H%M%S")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _tmp_code_dir(self) -> str:
        return _path_convert(
            self.wandb_dir,
            f"{self.run_mode}-{self.timespec}-{self.run_id}",
            "tmp",
            "code",
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def colab_url(self) -> str | None:
        """The URL to the Colab notebook, if running in Colab."""
        if not self._colab:
            return None
        if self.x_jupyter_path and self.x_jupyter_path.startswith("fileId="):
            unescaped = unquote(self.x_jupyter_path)
            return "https://colab.research.google.com/notebook#" + unescaped
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deployment(self) -> Literal["local", "cloud"]:
        return "local" if self.is_local else "cloud"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def files_dir(self) -> str:
        """Absolute path to the local directory where the run's files are stored."""
        return self.x_files_dir or _path_convert(
            self.wandb_dir,
            f"{self.run_mode}-{self.timespec}-{self.run_id}",
            "files",
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_local(self) -> bool:
        return str(self.base_url) != "https://api.wandb.ai"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_dir(self) -> str:
        """The directory for storing log files."""
        return _path_convert(
            self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", "logs"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_internal(self) -> str:
        """The path to the file to use for internal logs."""
        return _path_convert(self.log_dir, "debug-internal.log")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_symlink_internal(self) -> str:
        """The path to the symlink to the internal log file of the most recent run."""
        return _path_convert(self.wandb_dir, "debug-internal.log")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_symlink_user(self) -> str:
        """The path to the symlink to the user-process log file of the most recent run."""
        return _path_convert(self.wandb_dir, "debug.log")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_user(self) -> str:
        """The path to the file to use for user-process logs."""
        return _path_convert(self.log_dir, "debug.log")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_url(self) -> str:
        """The W&B URL where the project can be viewed."""
        project_url = self._project_url_base()
        if not project_url:
            return ""

        query = self._get_url_query_string()

        return f"{project_url}{query}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resume_fname(self) -> str:
        """The path to the resume file."""
        return _path_convert(self.wandb_dir, "wandb-resume.json")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def run_mode(self) -> Literal["run", "offline-run"]:
        return "run" if not self._offline else "offline-run"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def run_url(self) -> str:
        """The W&B URL where the run can be viewed."""
        project_url = self._project_url_base()
        if not all([project_url, self.run_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/runs/{quote(self.run_id or '')}{query}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def settings_workspace(self) -> str:
        """The path to the workspace settings file."""
        return _path_convert(self.wandb_dir, "settings")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sweep_url(self) -> str:
        """The W&B URL where the sweep can be viewed."""
        project_url = self._project_url_base()
        if not all([project_url, self.sweep_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/sweeps/{quote(self.sweep_id or '')}{query}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_dir(self) -> str:
        return _path_convert(
            self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_file(self) -> str:
        """Path to the append-only binary transaction log file."""
        return _path_convert(self.sync_dir, f"run-{self.run_id}.wandb")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_symlink_latest(self) -> str:
        return _path_convert(self.wandb_dir, "latest-run")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timespec(self) -> str:
        return self._start_datetime

    @computed_field  # type: ignore[prop-decorator]
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

    # Methods to collect and update settings from different sources.
    #
    # The Settings class does not track the source of the settings,
    # so it is up to the developer to ensure that the settings are applied
    # in the correct order. Most of the updates are done in
    # wandb/sdk/wandb_setup.py::_WandbSetup._settings_setup.

    def update_from_system_config_file(self):
        """Update settings from the system config file."""
        if not self.settings_system or not os.path.exists(self.settings_system):
            return
        for key, value in self._load_config_file(self.settings_system).items():
            if value is not None:
                setattr(self, key, value)

    def update_from_workspace_config_file(self):
        """Update settings from the workspace config file."""
        if not self.settings_workspace or not os.path.exists(self.settings_workspace):
            return
        for key, value in self._load_config_file(self.settings_workspace).items():
            if value is not None:
                setattr(self, key, value)

    def update_from_env_vars(self, environ: dict[str, Any]):
        """Update settings from environment variables."""
        env_prefix: str = "WANDB_"
        private_env_prefix: str = env_prefix + "_"
        special_env_var_names = {
            "WANDB_DISABLE_SERVICE": "x_disable_service",
            "WANDB_SERVICE_TRANSPORT": "x_service_transport",
            "WANDB_DIR": "root_dir",
            "WANDB_NAME": "run_name",
            "WANDB_NOTES": "run_notes",
            "WANDB_TAGS": "run_tags",
            "WANDB_JOB_TYPE": "run_job_type",
            "WANDB_HTTP_TIMEOUT": "x_graphql_timeout_seconds",
            "WANDB_FILE_PUSHER_TIMEOUT": "x_file_transfer_timeout_seconds",
            "WANDB_USER_EMAIL": "email",
        }
        env = dict()
        for setting, value in environ.items():
            if not setting.startswith(env_prefix):
                continue

            if setting in special_env_var_names:
                key = special_env_var_names[setting]
            elif setting.startswith(private_env_prefix):
                key = "x_" + setting[len(private_env_prefix) :].lower()
            else:
                # otherwise, strip the prefix and convert to lowercase
                key = setting[len(env_prefix) :].lower()

            if key in self.__dict__:
                if key in ("ignore_globs", "run_tags"):
                    value = value.split(",")
                env[key] = value

        for key, value in env.items():
            if value is not None:
                setattr(self, key, value)

    def update_from_system_environment(self):
        """Update settings from the system environment."""
        # For code saving, only allow env var override if value from server is true, or
        # if no preference was specified.
        if (self.save_code is True or self.save_code is None) and (
            os.getenv(env.SAVE_CODE) is not None
            or os.getenv(env.DISABLE_CODE) is not None
        ):
            self.save_code = env.should_save_code()

        if os.getenv(env.DISABLE_GIT) is not None:
            self.disable_git = env.disable_git()

        # Attempt to get notebook information if not already set by the user
        if self._jupyter and (self.notebook_name is None or self.notebook_name == ""):
            meta = wandb.jupyter.notebook_metadata(self.silent)  # type: ignore
            self.x_jupyter_path = meta.get("path")
            self.x_jupyter_name = meta.get("name")
            self.x_jupyter_root = meta.get("root")
        elif (
            self._jupyter
            and self.notebook_name is not None
            and os.path.exists(self.notebook_name)
        ):
            self.x_jupyter_path = self.notebook_name
            self.x_jupyter_name = self.notebook_name
            self.x_jupyter_root = os.getcwd()
        elif self._jupyter:
            wandb.termwarn(
                "WANDB_NOTEBOOK_NAME should be a path to a notebook file, "
                f"couldn't find {self.notebook_name}.",
            )

        # host is populated by update_from_env_vars if the corresponding env
        # vars exist -- but if they don't, we'll fill them in here.
        if self.host is None:
            self.host = socket.gethostname()  # type: ignore

        _executable = (
            self.x_executable
            or os.environ.get(env._EXECUTABLE)
            or sys.executable
            or shutil.which("python3")
            or "python3"
        )
        self.x_executable = _executable

        if self.docker is None:
            self.docker = env.get_docker(util.image_id_from_k8s())

        # proceed if not in CLI mode
        if self.x_cli_only_mode:
            return

        program = self.program or self._get_program()

        if program is not None:
            try:
                root = (
                    GitRepo().root or os.getcwd()
                    if not self.disable_git
                    else os.getcwd()
                )
            except Exception:
                # if the git command fails, fall back to the current working directory
                root = os.getcwd()

            self.program_relpath = self.program_relpath or self._get_program_relpath(
                program, root
            )
            program_abspath = os.path.abspath(
                os.path.join(root, os.path.relpath(os.getcwd(), root), program)
            )
            if os.path.exists(program_abspath):
                self.program_abspath = program_abspath
        else:
            program = "<python with no main file>"

        self.program = program

    def update_from_dict(self, settings: dict[str, Any]) -> None:
        """Update settings from a dictionary."""
        for key, value in dict(settings).items():
            if value is not None:
                setattr(self, key, value)

    def update_from_settings(self, settings: Settings) -> None:
        """Update settings from another instance of `Settings`."""
        d = {field: getattr(settings, field) for field in settings.model_fields_set}
        if d:
            self.update_from_dict(d)

    # Helper methods.

    def to_proto(self) -> wandb_settings_pb2.Settings:
        """Generate a protobuf representation of the settings."""
        settings_proto = wandb_settings_pb2.Settings()
        for k, v in self.model_dump(exclude_none=True).items():
            # special case for x_stats_open_metrics_filters
            if k == "x_stats_open_metrics_filters":
                if isinstance(v, (list, set, tuple)):
                    setting = getattr(settings_proto, k)
                    setting.sequence.value.extend(v)
                elif isinstance(v, dict):
                    setting = getattr(settings_proto, k)
                    for key, value in v.items():
                        for kk, vv in value.items():
                            setting.mapping.value[key].value[kk] = vv
                else:
                    raise TypeError(f"Unsupported type {type(v)} for setting {k}")
                continue

            # special case for RunMoment fields
            if k in ("fork_from", "resume_from"):
                run_moment = RunMoment(
                    run=v.get("run"),
                    value=v.get("value"),
                    metric=v.get("metric"),
                )
                getattr(settings_proto, k).CopyFrom(
                    wandb_settings_pb2.RunMoment(
                        run=run_moment.run,
                        value=run_moment.value,
                        metric=run_moment.metric,
                    )
                )
                continue

            if isinstance(v, bool):
                getattr(settings_proto, k).CopyFrom(BoolValue(value=v))
            elif isinstance(v, int):
                getattr(settings_proto, k).CopyFrom(Int32Value(value=v))
            elif isinstance(v, float):
                getattr(settings_proto, k).CopyFrom(DoubleValue(value=v))
            elif isinstance(v, str):
                getattr(settings_proto, k).CopyFrom(StringValue(value=v))
            elif isinstance(v, (list, set, tuple)):
                # we only support sequences of strings for now
                sequence = getattr(settings_proto, k)
                sequence.value.extend(v)
            elif isinstance(v, dict):
                mapping = getattr(settings_proto, k)
                for key, value in v.items():
                    # we only support dicts with string values for now
                    mapping.value[key] = value
            elif v is None:
                # None means that the setting value was not set.
                pass
            else:
                raise TypeError(f"Unsupported type {type(v)} for setting {k}")

        return settings_proto

    @staticmethod
    def validate_url(url: str) -> None:
        """Validate a URL string."""
        url_validator = SchemaValidator(
            core_schema.url_schema(
                allowed_schemes=["http", "https"],
                strict=True,
            )
        )
        url_validator.validate_python(url)

    def _get_program(self) -> str | None:
        """Get the program that started the current process."""
        if not self._jupyter:
            # If not in a notebook, try to get the program from the environment
            # or the __main__ module for scripts run as `python -m ...`.
            program = os.getenv(env.PROGRAM)
            if program is not None:
                return program
            try:
                import __main__

                if __main__.__spec__ is None:
                    return __main__.__file__
                return f"-m {__main__.__spec__.name}"
            except (ImportError, AttributeError):
                return None
        else:
            # If in a notebook, try to get the program from the notebook metadata.
            if self.notebook_name:
                return self.notebook_name

            if not self.x_jupyter_path:
                return self.program

            if self.x_jupyter_path.startswith("fileId="):
                return self.x_jupyter_name
            else:
                return self.x_jupyter_path

    @staticmethod
    def _get_program_relpath(program: str, root: str | None = None) -> str | None:
        """Get the relative path to the program from the root directory."""
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
    def _load_config_file(file_name: str, section: str = "default") -> dict:
        """Load a config file and return the settings for a given section."""
        parser = configparser.ConfigParser()
        parser.add_section(section)
        parser.read(file_name)
        config: dict[str, Any] = dict()
        for k in parser[section]:
            config[k] = parser[section][k]
            if k == "ignore_globs":
                config[k] = config[k].split(",")
        return config

    def _project_url_base(self) -> str:
        """Construct the base URL for the project."""
        if not all([self.entity, self.project]):
            return ""

        app_url = util.app_url(self.base_url)
        return f"{app_url}/{quote(self.entity or '')}/{quote(self.project or '')}"

    def _get_url_query_string(self) -> str:
        """Construct the query string for project, run, and sweep URLs."""
        # TODO: remove dependency on Api()
        if self.anonymous not in ["allow", "must"]:
            return ""

        api_key = apikey.api_key(settings=self)

        return f"?{urlencode({'apiKey': api_key})}"

    @staticmethod
    def _runmoment_preprocessor(val: RunMoment | str | None) -> RunMoment | None:
        """Preprocess the setting for forking or resuming a run."""
        if isinstance(val, RunMoment) or val is None:
            return val
        elif isinstance(val, str):
            return RunMoment.from_uri(val)
