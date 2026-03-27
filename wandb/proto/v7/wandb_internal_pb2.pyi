import datetime

from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from wandb.proto import wandb_base_pb2 as _wandb_base_pb2
from wandb.proto import wandb_telemetry_pb2 as _wandb_telemetry_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ServerFeature(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SERVER_FEATURE_UNSPECIFIED: _ClassVar[ServerFeature]
    LARGE_FILENAMES: _ClassVar[ServerFeature]
    ARTIFACT_TAGS: _ClassVar[ServerFeature]
    CLIENT_IDS: _ClassVar[ServerFeature]
    ARTIFACT_REGISTRY_SEARCH: _ClassVar[ServerFeature]
    STRUCTURED_CONSOLE_LOGS: _ClassVar[ServerFeature]
    ARTIFACT_COLLECTION_MEMBERSHIP_FILES: _ClassVar[ServerFeature]
    ARTIFACT_COLLECTION_MEMBERSHIP_FILE_DOWNLOAD_HANDLER: _ClassVar[ServerFeature]
    USE_ARTIFACT_WITH_ENTITY_AND_PROJECT_INFORMATION: _ClassVar[ServerFeature]
    EXPAND_DEFINED_METRIC_GLOBS: _ClassVar[ServerFeature]
    AUTOMATION_EVENT_RUN_METRIC: _ClassVar[ServerFeature]
    AUTOMATION_EVENT_RUN_METRIC_CHANGE: _ClassVar[ServerFeature]
    AUTOMATION_ACTION_NO_OP: _ClassVar[ServerFeature]
    INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION: _ClassVar[ServerFeature]
    PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP: _ClassVar[ServerFeature]
    ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: _ClassVar[ServerFeature]
    TOTAL_COUNT_IN_FILE_CONNECTION: _ClassVar[ServerFeature]
    ARTIFACT_COLLECTIONS_FILTERING_SORTING: _ClassVar[ServerFeature]
    ARTIFACT_V2_DOWNLOAD_HANDLER_SUPPORTS_ARTIFACT_ID: _ClassVar[ServerFeature]
SERVER_FEATURE_UNSPECIFIED: ServerFeature
LARGE_FILENAMES: ServerFeature
ARTIFACT_TAGS: ServerFeature
CLIENT_IDS: ServerFeature
ARTIFACT_REGISTRY_SEARCH: ServerFeature
STRUCTURED_CONSOLE_LOGS: ServerFeature
ARTIFACT_COLLECTION_MEMBERSHIP_FILES: ServerFeature
ARTIFACT_COLLECTION_MEMBERSHIP_FILE_DOWNLOAD_HANDLER: ServerFeature
USE_ARTIFACT_WITH_ENTITY_AND_PROJECT_INFORMATION: ServerFeature
EXPAND_DEFINED_METRIC_GLOBS: ServerFeature
AUTOMATION_EVENT_RUN_METRIC: ServerFeature
AUTOMATION_EVENT_RUN_METRIC_CHANGE: ServerFeature
AUTOMATION_ACTION_NO_OP: ServerFeature
INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION: ServerFeature
PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP: ServerFeature
ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: ServerFeature
TOTAL_COUNT_IN_FILE_CONNECTION: ServerFeature
ARTIFACT_COLLECTIONS_FILTERING_SORTING: ServerFeature
ARTIFACT_V2_DOWNLOAD_HANDLER_SUPPORTS_ARTIFACT_ID: ServerFeature

class Record(_message.Message):
    __slots__ = ("num", "history", "summary", "output", "config", "files", "stats", "artifact", "tbrecord", "alert", "telemetry", "metric", "output_raw", "run", "exit", "final", "header", "footer", "preempting", "noop_link_artifact", "use_artifact", "environment", "request", "control", "uuid", "_info")
    NUM_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    STATS_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    TBRECORD_FIELD_NUMBER: _ClassVar[int]
    ALERT_FIELD_NUMBER: _ClassVar[int]
    TELEMETRY_FIELD_NUMBER: _ClassVar[int]
    METRIC_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_RAW_FIELD_NUMBER: _ClassVar[int]
    RUN_FIELD_NUMBER: _ClassVar[int]
    EXIT_FIELD_NUMBER: _ClassVar[int]
    FINAL_FIELD_NUMBER: _ClassVar[int]
    HEADER_FIELD_NUMBER: _ClassVar[int]
    FOOTER_FIELD_NUMBER: _ClassVar[int]
    PREEMPTING_FIELD_NUMBER: _ClassVar[int]
    NOOP_LINK_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    USE_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    ENVIRONMENT_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    num: int
    history: HistoryRecord
    summary: SummaryRecord
    output: OutputRecord
    config: ConfigRecord
    files: FilesRecord
    stats: StatsRecord
    artifact: ArtifactRecord
    tbrecord: TBRecord
    alert: AlertRecord
    telemetry: _wandb_telemetry_pb2.TelemetryRecord
    metric: MetricRecord
    output_raw: OutputRawRecord
    run: RunRecord
    exit: RunExitRecord
    final: FinalRecord
    header: HeaderRecord
    footer: FooterRecord
    preempting: RunPreemptingRecord
    noop_link_artifact: _empty_pb2.Empty
    use_artifact: UseArtifactRecord
    environment: EnvironmentRecord
    request: Request
    control: Control
    uuid: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, num: _Optional[int] = ..., history: _Optional[_Union[HistoryRecord, _Mapping]] = ..., summary: _Optional[_Union[SummaryRecord, _Mapping]] = ..., output: _Optional[_Union[OutputRecord, _Mapping]] = ..., config: _Optional[_Union[ConfigRecord, _Mapping]] = ..., files: _Optional[_Union[FilesRecord, _Mapping]] = ..., stats: _Optional[_Union[StatsRecord, _Mapping]] = ..., artifact: _Optional[_Union[ArtifactRecord, _Mapping]] = ..., tbrecord: _Optional[_Union[TBRecord, _Mapping]] = ..., alert: _Optional[_Union[AlertRecord, _Mapping]] = ..., telemetry: _Optional[_Union[_wandb_telemetry_pb2.TelemetryRecord, _Mapping]] = ..., metric: _Optional[_Union[MetricRecord, _Mapping]] = ..., output_raw: _Optional[_Union[OutputRawRecord, _Mapping]] = ..., run: _Optional[_Union[RunRecord, _Mapping]] = ..., exit: _Optional[_Union[RunExitRecord, _Mapping]] = ..., final: _Optional[_Union[FinalRecord, _Mapping]] = ..., header: _Optional[_Union[HeaderRecord, _Mapping]] = ..., footer: _Optional[_Union[FooterRecord, _Mapping]] = ..., preempting: _Optional[_Union[RunPreemptingRecord, _Mapping]] = ..., noop_link_artifact: _Optional[_Union[_empty_pb2.Empty, _Mapping]] = ..., use_artifact: _Optional[_Union[UseArtifactRecord, _Mapping]] = ..., environment: _Optional[_Union[EnvironmentRecord, _Mapping]] = ..., request: _Optional[_Union[Request, _Mapping]] = ..., control: _Optional[_Union[Control, _Mapping]] = ..., uuid: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class Control(_message.Message):
    __slots__ = ("req_resp", "local", "relay_id", "mailbox_slot", "always_send", "flow_control", "end_offset", "connection_id")
    REQ_RESP_FIELD_NUMBER: _ClassVar[int]
    LOCAL_FIELD_NUMBER: _ClassVar[int]
    RELAY_ID_FIELD_NUMBER: _ClassVar[int]
    MAILBOX_SLOT_FIELD_NUMBER: _ClassVar[int]
    ALWAYS_SEND_FIELD_NUMBER: _ClassVar[int]
    FLOW_CONTROL_FIELD_NUMBER: _ClassVar[int]
    END_OFFSET_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_ID_FIELD_NUMBER: _ClassVar[int]
    req_resp: bool
    local: bool
    relay_id: str
    mailbox_slot: str
    always_send: bool
    flow_control: bool
    end_offset: int
    connection_id: str
    def __init__(self, req_resp: _Optional[bool] = ..., local: _Optional[bool] = ..., relay_id: _Optional[str] = ..., mailbox_slot: _Optional[str] = ..., always_send: _Optional[bool] = ..., flow_control: _Optional[bool] = ..., end_offset: _Optional[int] = ..., connection_id: _Optional[str] = ...) -> None: ...

class Result(_message.Message):
    __slots__ = ("run_result", "exit_result", "log_result", "summary_result", "output_result", "config_result", "response", "control", "uuid", "_info")
    RUN_RESULT_FIELD_NUMBER: _ClassVar[int]
    EXIT_RESULT_FIELD_NUMBER: _ClassVar[int]
    LOG_RESULT_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_RESULT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_RESULT_FIELD_NUMBER: _ClassVar[int]
    CONFIG_RESULT_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    run_result: RunUpdateResult
    exit_result: RunExitResult
    log_result: HistoryResult
    summary_result: SummaryResult
    output_result: OutputResult
    config_result: ConfigResult
    response: Response
    control: Control
    uuid: str
    _info: _wandb_base_pb2._ResultInfo
    def __init__(self, run_result: _Optional[_Union[RunUpdateResult, _Mapping]] = ..., exit_result: _Optional[_Union[RunExitResult, _Mapping]] = ..., log_result: _Optional[_Union[HistoryResult, _Mapping]] = ..., summary_result: _Optional[_Union[SummaryResult, _Mapping]] = ..., output_result: _Optional[_Union[OutputResult, _Mapping]] = ..., config_result: _Optional[_Union[ConfigResult, _Mapping]] = ..., response: _Optional[_Union[Response, _Mapping]] = ..., control: _Optional[_Union[Control, _Mapping]] = ..., uuid: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._ResultInfo, _Mapping]] = ...) -> None: ...

class FinalRecord(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class VersionInfo(_message.Message):
    __slots__ = ("producer", "min_consumer", "_info")
    PRODUCER_FIELD_NUMBER: _ClassVar[int]
    MIN_CONSUMER_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    producer: str
    min_consumer: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, producer: _Optional[str] = ..., min_consumer: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class HeaderRecord(_message.Message):
    __slots__ = ("version_info", "_info")
    VERSION_INFO_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    version_info: VersionInfo
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, version_info: _Optional[_Union[VersionInfo, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class FooterRecord(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class BranchPoint(_message.Message):
    __slots__ = ("run", "value", "metric")
    RUN_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    METRIC_FIELD_NUMBER: _ClassVar[int]
    run: str
    value: float
    metric: str
    def __init__(self, run: _Optional[str] = ..., value: _Optional[float] = ..., metric: _Optional[str] = ...) -> None: ...

class RunRecord(_message.Message):
    __slots__ = ("run_id", "entity", "project", "config", "summary", "run_group", "job_type", "display_name", "notes", "tags", "settings", "sweep_id", "host", "starting_step", "storage_id", "start_time", "resumed", "telemetry", "runtime", "git", "forked", "branch_point", "_info")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    RUN_GROUP_FIELD_NUMBER: _ClassVar[int]
    JOB_TYPE_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    SWEEP_ID_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    STARTING_STEP_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    RESUMED_FIELD_NUMBER: _ClassVar[int]
    TELEMETRY_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    GIT_FIELD_NUMBER: _ClassVar[int]
    FORKED_FIELD_NUMBER: _ClassVar[int]
    BRANCH_POINT_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    entity: str
    project: str
    config: ConfigRecord
    summary: SummaryRecord
    run_group: str
    job_type: str
    display_name: str
    notes: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    settings: SettingsRecord
    sweep_id: str
    host: str
    starting_step: int
    storage_id: str
    start_time: _timestamp_pb2.Timestamp
    resumed: bool
    telemetry: _wandb_telemetry_pb2.TelemetryRecord
    runtime: int
    git: GitRepoRecord
    forked: bool
    branch_point: BranchPoint
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, run_id: _Optional[str] = ..., entity: _Optional[str] = ..., project: _Optional[str] = ..., config: _Optional[_Union[ConfigRecord, _Mapping]] = ..., summary: _Optional[_Union[SummaryRecord, _Mapping]] = ..., run_group: _Optional[str] = ..., job_type: _Optional[str] = ..., display_name: _Optional[str] = ..., notes: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., settings: _Optional[_Union[SettingsRecord, _Mapping]] = ..., sweep_id: _Optional[str] = ..., host: _Optional[str] = ..., starting_step: _Optional[int] = ..., storage_id: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., resumed: _Optional[bool] = ..., telemetry: _Optional[_Union[_wandb_telemetry_pb2.TelemetryRecord, _Mapping]] = ..., runtime: _Optional[int] = ..., git: _Optional[_Union[GitRepoRecord, _Mapping]] = ..., forked: _Optional[bool] = ..., branch_point: _Optional[_Union[BranchPoint, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class GitRepoRecord(_message.Message):
    __slots__ = ("remote_url", "commit")
    REMOTE_URL_FIELD_NUMBER: _ClassVar[int]
    COMMIT_FIELD_NUMBER: _ClassVar[int]
    remote_url: str
    commit: str
    def __init__(self, remote_url: _Optional[str] = ..., commit: _Optional[str] = ...) -> None: ...

class RunUpdateResult(_message.Message):
    __slots__ = ("run", "error")
    RUN_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    run: RunRecord
    error: ErrorInfo
    def __init__(self, run: _Optional[_Union[RunRecord, _Mapping]] = ..., error: _Optional[_Union[ErrorInfo, _Mapping]] = ...) -> None: ...

class ErrorInfo(_message.Message):
    __slots__ = ("message", "code")
    class ErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNKNOWN: _ClassVar[ErrorInfo.ErrorCode]
        COMMUNICATION: _ClassVar[ErrorInfo.ErrorCode]
        AUTHENTICATION: _ClassVar[ErrorInfo.ErrorCode]
        USAGE: _ClassVar[ErrorInfo.ErrorCode]
        UNSUPPORTED: _ClassVar[ErrorInfo.ErrorCode]
    UNKNOWN: ErrorInfo.ErrorCode
    COMMUNICATION: ErrorInfo.ErrorCode
    AUTHENTICATION: ErrorInfo.ErrorCode
    USAGE: ErrorInfo.ErrorCode
    UNSUPPORTED: ErrorInfo.ErrorCode
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    message: str
    code: ErrorInfo.ErrorCode
    def __init__(self, message: _Optional[str] = ..., code: _Optional[_Union[ErrorInfo.ErrorCode, str]] = ...) -> None: ...

class RunExitRecord(_message.Message):
    __slots__ = ("exit_code", "runtime", "_info")
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    exit_code: int
    runtime: int
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, exit_code: _Optional[int] = ..., runtime: _Optional[int] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class RunExitResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RunPreemptingRecord(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class RunPreemptingResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SettingsRecord(_message.Message):
    __slots__ = ("item", "_info")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[SettingsItem]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, item: _Optional[_Iterable[_Union[SettingsItem, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class SettingsItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class HistoryStep(_message.Message):
    __slots__ = ("num",)
    NUM_FIELD_NUMBER: _ClassVar[int]
    num: int
    def __init__(self, num: _Optional[int] = ...) -> None: ...

class HistoryRecord(_message.Message):
    __slots__ = ("item", "step", "_info")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[HistoryItem]
    step: HistoryStep
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, item: _Optional[_Iterable[_Union[HistoryItem, _Mapping]]] = ..., step: _Optional[_Union[HistoryStep, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class HistoryItem(_message.Message):
    __slots__ = ("key", "nested_key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    NESTED_KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    nested_key: _containers.RepeatedScalarFieldContainer[str]
    value_json: str
    def __init__(self, key: _Optional[str] = ..., nested_key: _Optional[_Iterable[str]] = ..., value_json: _Optional[str] = ...) -> None: ...

class HistoryResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OutputRecord(_message.Message):
    __slots__ = ("output_type", "timestamp", "line", "_info")
    class OutputType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STDERR: _ClassVar[OutputRecord.OutputType]
        STDOUT: _ClassVar[OutputRecord.OutputType]
    STDERR: OutputRecord.OutputType
    STDOUT: OutputRecord.OutputType
    OUTPUT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    LINE_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    output_type: OutputRecord.OutputType
    timestamp: _timestamp_pb2.Timestamp
    line: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, output_type: _Optional[_Union[OutputRecord.OutputType, str]] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., line: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class OutputResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OutputRawRecord(_message.Message):
    __slots__ = ("output_type", "timestamp", "line", "_info")
    class OutputType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STDERR: _ClassVar[OutputRawRecord.OutputType]
        STDOUT: _ClassVar[OutputRawRecord.OutputType]
    STDERR: OutputRawRecord.OutputType
    STDOUT: OutputRawRecord.OutputType
    OUTPUT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    LINE_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    output_type: OutputRawRecord.OutputType
    timestamp: _timestamp_pb2.Timestamp
    line: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, output_type: _Optional[_Union[OutputRawRecord.OutputType, str]] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., line: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class OutputRawResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MetricRecord(_message.Message):
    __slots__ = ("name", "glob_name", "step_metric", "step_metric_index", "options", "summary", "goal", "_control", "expanded_from_glob", "_info")
    class MetricGoal(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        GOAL_UNSET: _ClassVar[MetricRecord.MetricGoal]
        GOAL_MINIMIZE: _ClassVar[MetricRecord.MetricGoal]
        GOAL_MAXIMIZE: _ClassVar[MetricRecord.MetricGoal]
    GOAL_UNSET: MetricRecord.MetricGoal
    GOAL_MINIMIZE: MetricRecord.MetricGoal
    GOAL_MAXIMIZE: MetricRecord.MetricGoal
    NAME_FIELD_NUMBER: _ClassVar[int]
    GLOB_NAME_FIELD_NUMBER: _ClassVar[int]
    STEP_METRIC_FIELD_NUMBER: _ClassVar[int]
    STEP_METRIC_INDEX_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    GOAL_FIELD_NUMBER: _ClassVar[int]
    _CONTROL_FIELD_NUMBER: _ClassVar[int]
    EXPANDED_FROM_GLOB_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    name: str
    glob_name: str
    step_metric: str
    step_metric_index: int
    options: MetricOptions
    summary: MetricSummary
    goal: MetricRecord.MetricGoal
    _control: MetricControl
    expanded_from_glob: bool
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, name: _Optional[str] = ..., glob_name: _Optional[str] = ..., step_metric: _Optional[str] = ..., step_metric_index: _Optional[int] = ..., options: _Optional[_Union[MetricOptions, _Mapping]] = ..., summary: _Optional[_Union[MetricSummary, _Mapping]] = ..., goal: _Optional[_Union[MetricRecord.MetricGoal, str]] = ..., _control: _Optional[_Union[MetricControl, _Mapping]] = ..., expanded_from_glob: _Optional[bool] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class MetricResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MetricOptions(_message.Message):
    __slots__ = ("step_sync", "hidden", "defined")
    STEP_SYNC_FIELD_NUMBER: _ClassVar[int]
    HIDDEN_FIELD_NUMBER: _ClassVar[int]
    DEFINED_FIELD_NUMBER: _ClassVar[int]
    step_sync: bool
    hidden: bool
    defined: bool
    def __init__(self, step_sync: _Optional[bool] = ..., hidden: _Optional[bool] = ..., defined: _Optional[bool] = ...) -> None: ...

class MetricControl(_message.Message):
    __slots__ = ("overwrite",)
    OVERWRITE_FIELD_NUMBER: _ClassVar[int]
    overwrite: bool
    def __init__(self, overwrite: _Optional[bool] = ...) -> None: ...

class MetricSummary(_message.Message):
    __slots__ = ("min", "max", "mean", "best", "last", "none", "copy", "first")
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    MEAN_FIELD_NUMBER: _ClassVar[int]
    BEST_FIELD_NUMBER: _ClassVar[int]
    LAST_FIELD_NUMBER: _ClassVar[int]
    NONE_FIELD_NUMBER: _ClassVar[int]
    COPY_FIELD_NUMBER: _ClassVar[int]
    FIRST_FIELD_NUMBER: _ClassVar[int]
    min: bool
    max: bool
    mean: bool
    best: bool
    last: bool
    none: bool
    copy: bool
    first: bool
    def __init__(self, min: _Optional[bool] = ..., max: _Optional[bool] = ..., mean: _Optional[bool] = ..., best: _Optional[bool] = ..., last: _Optional[bool] = ..., none: _Optional[bool] = ..., copy: _Optional[bool] = ..., first: _Optional[bool] = ...) -> None: ...

class ConfigRecord(_message.Message):
    __slots__ = ("update", "remove", "_info")
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    REMOVE_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    update: _containers.RepeatedCompositeFieldContainer[ConfigItem]
    remove: _containers.RepeatedCompositeFieldContainer[ConfigItem]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, update: _Optional[_Iterable[_Union[ConfigItem, _Mapping]]] = ..., remove: _Optional[_Iterable[_Union[ConfigItem, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ConfigItem(_message.Message):
    __slots__ = ("key", "nested_key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    NESTED_KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    nested_key: _containers.RepeatedScalarFieldContainer[str]
    value_json: str
    def __init__(self, key: _Optional[str] = ..., nested_key: _Optional[_Iterable[str]] = ..., value_json: _Optional[str] = ...) -> None: ...

class ConfigResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SummaryRecord(_message.Message):
    __slots__ = ("update", "remove", "_info")
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    REMOVE_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    update: _containers.RepeatedCompositeFieldContainer[SummaryItem]
    remove: _containers.RepeatedCompositeFieldContainer[SummaryItem]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, update: _Optional[_Iterable[_Union[SummaryItem, _Mapping]]] = ..., remove: _Optional[_Iterable[_Union[SummaryItem, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class SummaryItem(_message.Message):
    __slots__ = ("key", "nested_key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    NESTED_KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    nested_key: _containers.RepeatedScalarFieldContainer[str]
    value_json: str
    def __init__(self, key: _Optional[str] = ..., nested_key: _Optional[_Iterable[str]] = ..., value_json: _Optional[str] = ...) -> None: ...

class SummaryResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class FilesRecord(_message.Message):
    __slots__ = ("files", "_info")
    FILES_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedCompositeFieldContainer[FilesItem]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, files: _Optional[_Iterable[_Union[FilesItem, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class FilesItem(_message.Message):
    __slots__ = ("path", "policy", "type")
    class PolicyType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NOW: _ClassVar[FilesItem.PolicyType]
        END: _ClassVar[FilesItem.PolicyType]
        LIVE: _ClassVar[FilesItem.PolicyType]
    NOW: FilesItem.PolicyType
    END: FilesItem.PolicyType
    LIVE: FilesItem.PolicyType
    class FileType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OTHER: _ClassVar[FilesItem.FileType]
        WANDB: _ClassVar[FilesItem.FileType]
        MEDIA: _ClassVar[FilesItem.FileType]
        ARTIFACT: _ClassVar[FilesItem.FileType]
    OTHER: FilesItem.FileType
    WANDB: FilesItem.FileType
    MEDIA: FilesItem.FileType
    ARTIFACT: FilesItem.FileType
    PATH_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    path: str
    policy: FilesItem.PolicyType
    type: FilesItem.FileType
    def __init__(self, path: _Optional[str] = ..., policy: _Optional[_Union[FilesItem.PolicyType, str]] = ..., type: _Optional[_Union[FilesItem.FileType, str]] = ...) -> None: ...

class FilesResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatsRecord(_message.Message):
    __slots__ = ("stats_type", "timestamp", "item", "_info")
    class StatsType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SYSTEM: _ClassVar[StatsRecord.StatsType]
    SYSTEM: StatsRecord.StatsType
    STATS_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    ITEM_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    stats_type: StatsRecord.StatsType
    timestamp: _timestamp_pb2.Timestamp
    item: _containers.RepeatedCompositeFieldContainer[StatsItem]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, stats_type: _Optional[_Union[StatsRecord.StatsType, str]] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., item: _Optional[_Iterable[_Union[StatsItem, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class StatsItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class ArtifactRecord(_message.Message):
    __slots__ = ("run_id", "project", "entity", "type", "name", "digest", "description", "metadata", "user_created", "use_after_commit", "aliases", "manifest", "distributed_id", "finalize", "client_id", "sequence_client_id", "base_id", "ttl_duration_seconds", "tags", "incremental_beta1", "_info")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DIGEST_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    USER_CREATED_FIELD_NUMBER: _ClassVar[int]
    USE_AFTER_COMMIT_FIELD_NUMBER: _ClassVar[int]
    ALIASES_FIELD_NUMBER: _ClassVar[int]
    MANIFEST_FIELD_NUMBER: _ClassVar[int]
    DISTRIBUTED_ID_FIELD_NUMBER: _ClassVar[int]
    FINALIZE_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    BASE_ID_FIELD_NUMBER: _ClassVar[int]
    TTL_DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    INCREMENTAL_BETA1_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    project: str
    entity: str
    type: str
    name: str
    digest: str
    description: str
    metadata: str
    user_created: bool
    use_after_commit: bool
    aliases: _containers.RepeatedScalarFieldContainer[str]
    manifest: ArtifactManifest
    distributed_id: str
    finalize: bool
    client_id: str
    sequence_client_id: str
    base_id: str
    ttl_duration_seconds: int
    tags: _containers.RepeatedScalarFieldContainer[str]
    incremental_beta1: bool
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, run_id: _Optional[str] = ..., project: _Optional[str] = ..., entity: _Optional[str] = ..., type: _Optional[str] = ..., name: _Optional[str] = ..., digest: _Optional[str] = ..., description: _Optional[str] = ..., metadata: _Optional[str] = ..., user_created: _Optional[bool] = ..., use_after_commit: _Optional[bool] = ..., aliases: _Optional[_Iterable[str]] = ..., manifest: _Optional[_Union[ArtifactManifest, _Mapping]] = ..., distributed_id: _Optional[str] = ..., finalize: _Optional[bool] = ..., client_id: _Optional[str] = ..., sequence_client_id: _Optional[str] = ..., base_id: _Optional[str] = ..., ttl_duration_seconds: _Optional[int] = ..., tags: _Optional[_Iterable[str]] = ..., incremental_beta1: _Optional[bool] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ArtifactManifest(_message.Message):
    __slots__ = ("version", "storage_policy", "storage_policy_config", "contents", "manifest_file_path")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    STORAGE_POLICY_FIELD_NUMBER: _ClassVar[int]
    STORAGE_POLICY_CONFIG_FIELD_NUMBER: _ClassVar[int]
    CONTENTS_FIELD_NUMBER: _ClassVar[int]
    MANIFEST_FILE_PATH_FIELD_NUMBER: _ClassVar[int]
    version: int
    storage_policy: str
    storage_policy_config: _containers.RepeatedCompositeFieldContainer[StoragePolicyConfigItem]
    contents: _containers.RepeatedCompositeFieldContainer[ArtifactManifestEntry]
    manifest_file_path: str
    def __init__(self, version: _Optional[int] = ..., storage_policy: _Optional[str] = ..., storage_policy_config: _Optional[_Iterable[_Union[StoragePolicyConfigItem, _Mapping]]] = ..., contents: _Optional[_Iterable[_Union[ArtifactManifestEntry, _Mapping]]] = ..., manifest_file_path: _Optional[str] = ...) -> None: ...

class ArtifactManifestEntry(_message.Message):
    __slots__ = ("path", "digest", "ref", "size", "mimetype", "local_path", "birth_artifact_id", "skip_cache", "extra")
    PATH_FIELD_NUMBER: _ClassVar[int]
    DIGEST_FIELD_NUMBER: _ClassVar[int]
    REF_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    MIMETYPE_FIELD_NUMBER: _ClassVar[int]
    LOCAL_PATH_FIELD_NUMBER: _ClassVar[int]
    BIRTH_ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    SKIP_CACHE_FIELD_NUMBER: _ClassVar[int]
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    path: str
    digest: str
    ref: str
    size: int
    mimetype: str
    local_path: str
    birth_artifact_id: str
    skip_cache: bool
    extra: _containers.RepeatedCompositeFieldContainer[ExtraItem]
    def __init__(self, path: _Optional[str] = ..., digest: _Optional[str] = ..., ref: _Optional[str] = ..., size: _Optional[int] = ..., mimetype: _Optional[str] = ..., local_path: _Optional[str] = ..., birth_artifact_id: _Optional[str] = ..., skip_cache: _Optional[bool] = ..., extra: _Optional[_Iterable[_Union[ExtraItem, _Mapping]]] = ...) -> None: ...

class ExtraItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class StoragePolicyConfigItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class ArtifactResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LinkArtifactResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LinkArtifactRequest(_message.Message):
    __slots__ = ("client_id", "server_id", "portfolio_name", "portfolio_entity", "portfolio_project", "portfolio_aliases", "portfolio_organization", "_info")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_ID_FIELD_NUMBER: _ClassVar[int]
    PORTFOLIO_NAME_FIELD_NUMBER: _ClassVar[int]
    PORTFOLIO_ENTITY_FIELD_NUMBER: _ClassVar[int]
    PORTFOLIO_PROJECT_FIELD_NUMBER: _ClassVar[int]
    PORTFOLIO_ALIASES_FIELD_NUMBER: _ClassVar[int]
    PORTFOLIO_ORGANIZATION_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    server_id: str
    portfolio_name: str
    portfolio_entity: str
    portfolio_project: str
    portfolio_aliases: _containers.RepeatedScalarFieldContainer[str]
    portfolio_organization: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, client_id: _Optional[str] = ..., server_id: _Optional[str] = ..., portfolio_name: _Optional[str] = ..., portfolio_entity: _Optional[str] = ..., portfolio_project: _Optional[str] = ..., portfolio_aliases: _Optional[_Iterable[str]] = ..., portfolio_organization: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class LinkArtifactResponse(_message.Message):
    __slots__ = ("error_message", "version_index")
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VERSION_INDEX_FIELD_NUMBER: _ClassVar[int]
    error_message: str
    version_index: int
    def __init__(self, error_message: _Optional[str] = ..., version_index: _Optional[int] = ...) -> None: ...

class TBRecord(_message.Message):
    __slots__ = ("_info", "log_dir", "root_dir", "save")
    _INFO_FIELD_NUMBER: _ClassVar[int]
    LOG_DIR_FIELD_NUMBER: _ClassVar[int]
    ROOT_DIR_FIELD_NUMBER: _ClassVar[int]
    SAVE_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    log_dir: str
    root_dir: str
    save: bool
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ..., log_dir: _Optional[str] = ..., root_dir: _Optional[str] = ..., save: _Optional[bool] = ...) -> None: ...

class TBResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AlertRecord(_message.Message):
    __slots__ = ("title", "text", "level", "wait_duration", "_info")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    WAIT_DURATION_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    title: str
    text: str
    level: str
    wait_duration: int
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, title: _Optional[str] = ..., text: _Optional[str] = ..., level: _Optional[str] = ..., wait_duration: _Optional[int] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class AlertResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Request(_message.Message):
    __slots__ = ("stop_status", "network_status", "defer", "get_summary", "login", "pause", "resume", "poll_exit", "sampled_history", "partial_history", "run_start", "check_version", "log_artifact", "download_artifact", "keepalive", "run_status", "cancel", "internal_messages", "python_packages", "shutdown", "attach", "status", "server_info", "sender_mark", "sender_read", "status_report", "summary_record", "telemetry_record", "job_info", "get_system_metrics", "job_input", "link_artifact", "run_finish_without_exit", "sync_finish", "operations", "probe_system_info", "test_inject")
    STOP_STATUS_FIELD_NUMBER: _ClassVar[int]
    NETWORK_STATUS_FIELD_NUMBER: _ClassVar[int]
    DEFER_FIELD_NUMBER: _ClassVar[int]
    GET_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    LOGIN_FIELD_NUMBER: _ClassVar[int]
    PAUSE_FIELD_NUMBER: _ClassVar[int]
    RESUME_FIELD_NUMBER: _ClassVar[int]
    POLL_EXIT_FIELD_NUMBER: _ClassVar[int]
    SAMPLED_HISTORY_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_HISTORY_FIELD_NUMBER: _ClassVar[int]
    RUN_START_FIELD_NUMBER: _ClassVar[int]
    CHECK_VERSION_FIELD_NUMBER: _ClassVar[int]
    LOG_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    KEEPALIVE_FIELD_NUMBER: _ClassVar[int]
    RUN_STATUS_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    PYTHON_PACKAGES_FIELD_NUMBER: _ClassVar[int]
    SHUTDOWN_FIELD_NUMBER: _ClassVar[int]
    ATTACH_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SERVER_INFO_FIELD_NUMBER: _ClassVar[int]
    SENDER_MARK_FIELD_NUMBER: _ClassVar[int]
    SENDER_READ_FIELD_NUMBER: _ClassVar[int]
    STATUS_REPORT_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_RECORD_FIELD_NUMBER: _ClassVar[int]
    TELEMETRY_RECORD_FIELD_NUMBER: _ClassVar[int]
    JOB_INFO_FIELD_NUMBER: _ClassVar[int]
    GET_SYSTEM_METRICS_FIELD_NUMBER: _ClassVar[int]
    JOB_INPUT_FIELD_NUMBER: _ClassVar[int]
    LINK_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    RUN_FINISH_WITHOUT_EXIT_FIELD_NUMBER: _ClassVar[int]
    SYNC_FINISH_FIELD_NUMBER: _ClassVar[int]
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    PROBE_SYSTEM_INFO_FIELD_NUMBER: _ClassVar[int]
    TEST_INJECT_FIELD_NUMBER: _ClassVar[int]
    stop_status: StopStatusRequest
    network_status: NetworkStatusRequest
    defer: DeferRequest
    get_summary: GetSummaryRequest
    login: LoginRequest
    pause: PauseRequest
    resume: ResumeRequest
    poll_exit: PollExitRequest
    sampled_history: SampledHistoryRequest
    partial_history: PartialHistoryRequest
    run_start: RunStartRequest
    check_version: CheckVersionRequest
    log_artifact: LogArtifactRequest
    download_artifact: DownloadArtifactRequest
    keepalive: KeepaliveRequest
    run_status: RunStatusRequest
    cancel: CancelRequest
    internal_messages: InternalMessagesRequest
    python_packages: PythonPackagesRequest
    shutdown: ShutdownRequest
    attach: AttachRequest
    status: StatusRequest
    server_info: ServerInfoRequest
    sender_mark: SenderMarkRequest
    sender_read: SenderReadRequest
    status_report: StatusReportRequest
    summary_record: SummaryRecordRequest
    telemetry_record: TelemetryRecordRequest
    job_info: JobInfoRequest
    get_system_metrics: GetSystemMetricsRequest
    job_input: JobInputRequest
    link_artifact: LinkArtifactRequest
    run_finish_without_exit: RunFinishWithoutExitRequest
    sync_finish: SyncFinishRequest
    operations: OperationStatsRequest
    probe_system_info: ProbeSystemInfoRequest
    test_inject: TestInjectRequest
    def __init__(self, stop_status: _Optional[_Union[StopStatusRequest, _Mapping]] = ..., network_status: _Optional[_Union[NetworkStatusRequest, _Mapping]] = ..., defer: _Optional[_Union[DeferRequest, _Mapping]] = ..., get_summary: _Optional[_Union[GetSummaryRequest, _Mapping]] = ..., login: _Optional[_Union[LoginRequest, _Mapping]] = ..., pause: _Optional[_Union[PauseRequest, _Mapping]] = ..., resume: _Optional[_Union[ResumeRequest, _Mapping]] = ..., poll_exit: _Optional[_Union[PollExitRequest, _Mapping]] = ..., sampled_history: _Optional[_Union[SampledHistoryRequest, _Mapping]] = ..., partial_history: _Optional[_Union[PartialHistoryRequest, _Mapping]] = ..., run_start: _Optional[_Union[RunStartRequest, _Mapping]] = ..., check_version: _Optional[_Union[CheckVersionRequest, _Mapping]] = ..., log_artifact: _Optional[_Union[LogArtifactRequest, _Mapping]] = ..., download_artifact: _Optional[_Union[DownloadArtifactRequest, _Mapping]] = ..., keepalive: _Optional[_Union[KeepaliveRequest, _Mapping]] = ..., run_status: _Optional[_Union[RunStatusRequest, _Mapping]] = ..., cancel: _Optional[_Union[CancelRequest, _Mapping]] = ..., internal_messages: _Optional[_Union[InternalMessagesRequest, _Mapping]] = ..., python_packages: _Optional[_Union[PythonPackagesRequest, _Mapping]] = ..., shutdown: _Optional[_Union[ShutdownRequest, _Mapping]] = ..., attach: _Optional[_Union[AttachRequest, _Mapping]] = ..., status: _Optional[_Union[StatusRequest, _Mapping]] = ..., server_info: _Optional[_Union[ServerInfoRequest, _Mapping]] = ..., sender_mark: _Optional[_Union[SenderMarkRequest, _Mapping]] = ..., sender_read: _Optional[_Union[SenderReadRequest, _Mapping]] = ..., status_report: _Optional[_Union[StatusReportRequest, _Mapping]] = ..., summary_record: _Optional[_Union[SummaryRecordRequest, _Mapping]] = ..., telemetry_record: _Optional[_Union[TelemetryRecordRequest, _Mapping]] = ..., job_info: _Optional[_Union[JobInfoRequest, _Mapping]] = ..., get_system_metrics: _Optional[_Union[GetSystemMetricsRequest, _Mapping]] = ..., job_input: _Optional[_Union[JobInputRequest, _Mapping]] = ..., link_artifact: _Optional[_Union[LinkArtifactRequest, _Mapping]] = ..., run_finish_without_exit: _Optional[_Union[RunFinishWithoutExitRequest, _Mapping]] = ..., sync_finish: _Optional[_Union[SyncFinishRequest, _Mapping]] = ..., operations: _Optional[_Union[OperationStatsRequest, _Mapping]] = ..., probe_system_info: _Optional[_Union[ProbeSystemInfoRequest, _Mapping]] = ..., test_inject: _Optional[_Union[TestInjectRequest, _Mapping]] = ...) -> None: ...

class Response(_message.Message):
    __slots__ = ("keepalive_response", "stop_status_response", "network_status_response", "login_response", "get_summary_response", "poll_exit_response", "sampled_history_response", "run_start_response", "check_version_response", "log_artifact_response", "download_artifact_response", "run_status_response", "cancel_response", "internal_messages_response", "shutdown_response", "attach_response", "status_response", "server_info_response", "job_info_response", "get_system_metrics_response", "link_artifact_response", "sync_response", "run_finish_without_exit_response", "operations_response", "test_inject_response")
    KEEPALIVE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STOP_STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    NETWORK_STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    LOGIN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    GET_SUMMARY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    POLL_EXIT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SAMPLED_HISTORY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RUN_START_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CHECK_VERSION_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    LOG_ARTIFACT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_ARTIFACT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RUN_STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CANCEL_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_MESSAGES_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SHUTDOWN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ATTACH_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SERVER_INFO_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    JOB_INFO_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    GET_SYSTEM_METRICS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    LINK_ARTIFACT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SYNC_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RUN_FINISH_WITHOUT_EXIT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    OPERATIONS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    TEST_INJECT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    keepalive_response: KeepaliveResponse
    stop_status_response: StopStatusResponse
    network_status_response: NetworkStatusResponse
    login_response: LoginResponse
    get_summary_response: GetSummaryResponse
    poll_exit_response: PollExitResponse
    sampled_history_response: SampledHistoryResponse
    run_start_response: RunStartResponse
    check_version_response: CheckVersionResponse
    log_artifact_response: LogArtifactResponse
    download_artifact_response: DownloadArtifactResponse
    run_status_response: RunStatusResponse
    cancel_response: CancelResponse
    internal_messages_response: InternalMessagesResponse
    shutdown_response: ShutdownResponse
    attach_response: AttachResponse
    status_response: StatusResponse
    server_info_response: ServerInfoResponse
    job_info_response: JobInfoResponse
    get_system_metrics_response: GetSystemMetricsResponse
    link_artifact_response: LinkArtifactResponse
    sync_response: SyncResponse
    run_finish_without_exit_response: RunFinishWithoutExitResponse
    operations_response: OperationStatsResponse
    test_inject_response: TestInjectResponse
    def __init__(self, keepalive_response: _Optional[_Union[KeepaliveResponse, _Mapping]] = ..., stop_status_response: _Optional[_Union[StopStatusResponse, _Mapping]] = ..., network_status_response: _Optional[_Union[NetworkStatusResponse, _Mapping]] = ..., login_response: _Optional[_Union[LoginResponse, _Mapping]] = ..., get_summary_response: _Optional[_Union[GetSummaryResponse, _Mapping]] = ..., poll_exit_response: _Optional[_Union[PollExitResponse, _Mapping]] = ..., sampled_history_response: _Optional[_Union[SampledHistoryResponse, _Mapping]] = ..., run_start_response: _Optional[_Union[RunStartResponse, _Mapping]] = ..., check_version_response: _Optional[_Union[CheckVersionResponse, _Mapping]] = ..., log_artifact_response: _Optional[_Union[LogArtifactResponse, _Mapping]] = ..., download_artifact_response: _Optional[_Union[DownloadArtifactResponse, _Mapping]] = ..., run_status_response: _Optional[_Union[RunStatusResponse, _Mapping]] = ..., cancel_response: _Optional[_Union[CancelResponse, _Mapping]] = ..., internal_messages_response: _Optional[_Union[InternalMessagesResponse, _Mapping]] = ..., shutdown_response: _Optional[_Union[ShutdownResponse, _Mapping]] = ..., attach_response: _Optional[_Union[AttachResponse, _Mapping]] = ..., status_response: _Optional[_Union[StatusResponse, _Mapping]] = ..., server_info_response: _Optional[_Union[ServerInfoResponse, _Mapping]] = ..., job_info_response: _Optional[_Union[JobInfoResponse, _Mapping]] = ..., get_system_metrics_response: _Optional[_Union[GetSystemMetricsResponse, _Mapping]] = ..., link_artifact_response: _Optional[_Union[LinkArtifactResponse, _Mapping]] = ..., sync_response: _Optional[_Union[SyncResponse, _Mapping]] = ..., run_finish_without_exit_response: _Optional[_Union[RunFinishWithoutExitResponse, _Mapping]] = ..., operations_response: _Optional[_Union[OperationStatsResponse, _Mapping]] = ..., test_inject_response: _Optional[_Union[TestInjectResponse, _Mapping]] = ...) -> None: ...

class DeferRequest(_message.Message):
    __slots__ = ("state",)
    class DeferState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        BEGIN: _ClassVar[DeferRequest.DeferState]
        FLUSH_RUN: _ClassVar[DeferRequest.DeferState]
        FLUSH_STATS: _ClassVar[DeferRequest.DeferState]
        FLUSH_PARTIAL_HISTORY: _ClassVar[DeferRequest.DeferState]
        FLUSH_TB: _ClassVar[DeferRequest.DeferState]
        FLUSH_SUM: _ClassVar[DeferRequest.DeferState]
        FLUSH_DEBOUNCER: _ClassVar[DeferRequest.DeferState]
        FLUSH_OUTPUT: _ClassVar[DeferRequest.DeferState]
        FLUSH_JOB: _ClassVar[DeferRequest.DeferState]
        FLUSH_DIR: _ClassVar[DeferRequest.DeferState]
        FLUSH_FP: _ClassVar[DeferRequest.DeferState]
        JOIN_FP: _ClassVar[DeferRequest.DeferState]
        FLUSH_FS: _ClassVar[DeferRequest.DeferState]
        FLUSH_FINAL: _ClassVar[DeferRequest.DeferState]
        END: _ClassVar[DeferRequest.DeferState]
    BEGIN: DeferRequest.DeferState
    FLUSH_RUN: DeferRequest.DeferState
    FLUSH_STATS: DeferRequest.DeferState
    FLUSH_PARTIAL_HISTORY: DeferRequest.DeferState
    FLUSH_TB: DeferRequest.DeferState
    FLUSH_SUM: DeferRequest.DeferState
    FLUSH_DEBOUNCER: DeferRequest.DeferState
    FLUSH_OUTPUT: DeferRequest.DeferState
    FLUSH_JOB: DeferRequest.DeferState
    FLUSH_DIR: DeferRequest.DeferState
    FLUSH_FP: DeferRequest.DeferState
    JOIN_FP: DeferRequest.DeferState
    FLUSH_FS: DeferRequest.DeferState
    FLUSH_FINAL: DeferRequest.DeferState
    END: DeferRequest.DeferState
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: DeferRequest.DeferState
    def __init__(self, state: _Optional[_Union[DeferRequest.DeferState, str]] = ...) -> None: ...

class PauseRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class PauseResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResumeRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class ResumeResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LoginRequest(_message.Message):
    __slots__ = ("api_key", "_info")
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    api_key: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, api_key: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class LoginResponse(_message.Message):
    __slots__ = ("active_entity",)
    ACTIVE_ENTITY_FIELD_NUMBER: _ClassVar[int]
    active_entity: str
    def __init__(self, active_entity: _Optional[str] = ...) -> None: ...

class GetSummaryRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class GetSummaryResponse(_message.Message):
    __slots__ = ("item",)
    ITEM_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[SummaryItem]
    def __init__(self, item: _Optional[_Iterable[_Union[SummaryItem, _Mapping]]] = ...) -> None: ...

class GetSystemMetricsRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class SystemMetricSample(_message.Message):
    __slots__ = ("timestamp", "value")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    timestamp: _timestamp_pb2.Timestamp
    value: float
    def __init__(self, timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., value: _Optional[float] = ...) -> None: ...

class SystemMetricsBuffer(_message.Message):
    __slots__ = ("record",)
    RECORD_FIELD_NUMBER: _ClassVar[int]
    record: _containers.RepeatedCompositeFieldContainer[SystemMetricSample]
    def __init__(self, record: _Optional[_Iterable[_Union[SystemMetricSample, _Mapping]]] = ...) -> None: ...

class GetSystemMetricsResponse(_message.Message):
    __slots__ = ("system_metrics",)
    class SystemMetricsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: SystemMetricsBuffer
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[SystemMetricsBuffer, _Mapping]] = ...) -> None: ...
    SYSTEM_METRICS_FIELD_NUMBER: _ClassVar[int]
    system_metrics: _containers.MessageMap[str, SystemMetricsBuffer]
    def __init__(self, system_metrics: _Optional[_Mapping[str, SystemMetricsBuffer]] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("run_should_stop",)
    RUN_SHOULD_STOP_FIELD_NUMBER: _ClassVar[int]
    run_should_stop: bool
    def __init__(self, run_should_stop: _Optional[bool] = ...) -> None: ...

class StopStatusRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class StopStatusResponse(_message.Message):
    __slots__ = ("run_should_stop",)
    RUN_SHOULD_STOP_FIELD_NUMBER: _ClassVar[int]
    run_should_stop: bool
    def __init__(self, run_should_stop: _Optional[bool] = ...) -> None: ...

class NetworkStatusRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class NetworkStatusResponse(_message.Message):
    __slots__ = ("network_responses",)
    NETWORK_RESPONSES_FIELD_NUMBER: _ClassVar[int]
    network_responses: _containers.RepeatedCompositeFieldContainer[HttpResponse]
    def __init__(self, network_responses: _Optional[_Iterable[_Union[HttpResponse, _Mapping]]] = ...) -> None: ...

class HttpResponse(_message.Message):
    __slots__ = ("http_status_code", "http_response_text")
    HTTP_STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    HTTP_RESPONSE_TEXT_FIELD_NUMBER: _ClassVar[int]
    http_status_code: int
    http_response_text: str
    def __init__(self, http_status_code: _Optional[int] = ..., http_response_text: _Optional[str] = ...) -> None: ...

class InternalMessagesRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class InternalMessagesResponse(_message.Message):
    __slots__ = ("messages",)
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    messages: InternalMessages
    def __init__(self, messages: _Optional[_Union[InternalMessages, _Mapping]] = ...) -> None: ...

class InternalMessages(_message.Message):
    __slots__ = ("warning",)
    WARNING_FIELD_NUMBER: _ClassVar[int]
    warning: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, warning: _Optional[_Iterable[str]] = ...) -> None: ...

class PollExitRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class PollExitResponse(_message.Message):
    __slots__ = ("done", "exit_result", "pusher_stats", "file_counts", "operation_stats")
    DONE_FIELD_NUMBER: _ClassVar[int]
    EXIT_RESULT_FIELD_NUMBER: _ClassVar[int]
    PUSHER_STATS_FIELD_NUMBER: _ClassVar[int]
    FILE_COUNTS_FIELD_NUMBER: _ClassVar[int]
    OPERATION_STATS_FIELD_NUMBER: _ClassVar[int]
    done: bool
    exit_result: RunExitResult
    pusher_stats: FilePusherStats
    file_counts: FileCounts
    operation_stats: OperationStats
    def __init__(self, done: _Optional[bool] = ..., exit_result: _Optional[_Union[RunExitResult, _Mapping]] = ..., pusher_stats: _Optional[_Union[FilePusherStats, _Mapping]] = ..., file_counts: _Optional[_Union[FileCounts, _Mapping]] = ..., operation_stats: _Optional[_Union[OperationStats, _Mapping]] = ...) -> None: ...

class OperationStatsRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class OperationStatsResponse(_message.Message):
    __slots__ = ("operation_stats",)
    OPERATION_STATS_FIELD_NUMBER: _ClassVar[int]
    operation_stats: OperationStats
    def __init__(self, operation_stats: _Optional[_Union[OperationStats, _Mapping]] = ...) -> None: ...

class OperationStats(_message.Message):
    __slots__ = ("label", "operations", "total_operations")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    label: str
    operations: _containers.RepeatedCompositeFieldContainer[Operation]
    total_operations: int
    def __init__(self, label: _Optional[str] = ..., operations: _Optional[_Iterable[_Union[Operation, _Mapping]]] = ..., total_operations: _Optional[int] = ...) -> None: ...

class Operation(_message.Message):
    __slots__ = ("desc", "runtime_seconds", "progress", "error_status", "subtasks")
    DESC_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_SECONDS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_STATUS_FIELD_NUMBER: _ClassVar[int]
    SUBTASKS_FIELD_NUMBER: _ClassVar[int]
    desc: str
    runtime_seconds: float
    progress: str
    error_status: str
    subtasks: _containers.RepeatedCompositeFieldContainer[Operation]
    def __init__(self, desc: _Optional[str] = ..., runtime_seconds: _Optional[float] = ..., progress: _Optional[str] = ..., error_status: _Optional[str] = ..., subtasks: _Optional[_Iterable[_Union[Operation, _Mapping]]] = ...) -> None: ...

class SenderMarkRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SyncFinishRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SyncResponse(_message.Message):
    __slots__ = ("url", "error")
    URL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    url: str
    error: ErrorInfo
    def __init__(self, url: _Optional[str] = ..., error: _Optional[_Union[ErrorInfo, _Mapping]] = ...) -> None: ...

class SenderReadRequest(_message.Message):
    __slots__ = ("start_offset", "final_offset")
    START_OFFSET_FIELD_NUMBER: _ClassVar[int]
    FINAL_OFFSET_FIELD_NUMBER: _ClassVar[int]
    start_offset: int
    final_offset: int
    def __init__(self, start_offset: _Optional[int] = ..., final_offset: _Optional[int] = ...) -> None: ...

class StatusReportRequest(_message.Message):
    __slots__ = ("record_num", "sent_offset", "sync_time")
    RECORD_NUM_FIELD_NUMBER: _ClassVar[int]
    SENT_OFFSET_FIELD_NUMBER: _ClassVar[int]
    SYNC_TIME_FIELD_NUMBER: _ClassVar[int]
    record_num: int
    sent_offset: int
    sync_time: _timestamp_pb2.Timestamp
    def __init__(self, record_num: _Optional[int] = ..., sent_offset: _Optional[int] = ..., sync_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class SummaryRecordRequest(_message.Message):
    __slots__ = ("summary",)
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    summary: SummaryRecord
    def __init__(self, summary: _Optional[_Union[SummaryRecord, _Mapping]] = ...) -> None: ...

class TelemetryRecordRequest(_message.Message):
    __slots__ = ("telemetry",)
    TELEMETRY_FIELD_NUMBER: _ClassVar[int]
    telemetry: _wandb_telemetry_pb2.TelemetryRecord
    def __init__(self, telemetry: _Optional[_Union[_wandb_telemetry_pb2.TelemetryRecord, _Mapping]] = ...) -> None: ...

class ServerInfoRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class ServerInfoResponse(_message.Message):
    __slots__ = ("local_info", "server_messages")
    LOCAL_INFO_FIELD_NUMBER: _ClassVar[int]
    SERVER_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    local_info: LocalInfo
    server_messages: ServerMessages
    def __init__(self, local_info: _Optional[_Union[LocalInfo, _Mapping]] = ..., server_messages: _Optional[_Union[ServerMessages, _Mapping]] = ...) -> None: ...

class ServerMessages(_message.Message):
    __slots__ = ("item",)
    ITEM_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[ServerMessage]
    def __init__(self, item: _Optional[_Iterable[_Union[ServerMessage, _Mapping]]] = ...) -> None: ...

class ServerMessage(_message.Message):
    __slots__ = ("plain_text", "utf_text", "html_text", "type", "level")
    PLAIN_TEXT_FIELD_NUMBER: _ClassVar[int]
    UTF_TEXT_FIELD_NUMBER: _ClassVar[int]
    HTML_TEXT_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    plain_text: str
    utf_text: str
    html_text: str
    type: str
    level: int
    def __init__(self, plain_text: _Optional[str] = ..., utf_text: _Optional[str] = ..., html_text: _Optional[str] = ..., type: _Optional[str] = ..., level: _Optional[int] = ...) -> None: ...

class FileCounts(_message.Message):
    __slots__ = ("wandb_count", "media_count", "artifact_count", "other_count")
    WANDB_COUNT_FIELD_NUMBER: _ClassVar[int]
    MEDIA_COUNT_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_COUNT_FIELD_NUMBER: _ClassVar[int]
    OTHER_COUNT_FIELD_NUMBER: _ClassVar[int]
    wandb_count: int
    media_count: int
    artifact_count: int
    other_count: int
    def __init__(self, wandb_count: _Optional[int] = ..., media_count: _Optional[int] = ..., artifact_count: _Optional[int] = ..., other_count: _Optional[int] = ...) -> None: ...

class FilePusherStats(_message.Message):
    __slots__ = ("uploaded_bytes", "total_bytes", "deduped_bytes")
    UPLOADED_BYTES_FIELD_NUMBER: _ClassVar[int]
    TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    DEDUPED_BYTES_FIELD_NUMBER: _ClassVar[int]
    uploaded_bytes: int
    total_bytes: int
    deduped_bytes: int
    def __init__(self, uploaded_bytes: _Optional[int] = ..., total_bytes: _Optional[int] = ..., deduped_bytes: _Optional[int] = ...) -> None: ...

class FilesUploaded(_message.Message):
    __slots__ = ("files",)
    FILES_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, files: _Optional[_Iterable[str]] = ...) -> None: ...

class FileTransferInfoRequest(_message.Message):
    __slots__ = ("type", "path", "url", "size", "processed", "file_counts")
    class TransferType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Upload: _ClassVar[FileTransferInfoRequest.TransferType]
        Download: _ClassVar[FileTransferInfoRequest.TransferType]
    Upload: FileTransferInfoRequest.TransferType
    Download: FileTransferInfoRequest.TransferType
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    PROCESSED_FIELD_NUMBER: _ClassVar[int]
    FILE_COUNTS_FIELD_NUMBER: _ClassVar[int]
    type: FileTransferInfoRequest.TransferType
    path: str
    url: str
    size: int
    processed: int
    file_counts: FileCounts
    def __init__(self, type: _Optional[_Union[FileTransferInfoRequest.TransferType, str]] = ..., path: _Optional[str] = ..., url: _Optional[str] = ..., size: _Optional[int] = ..., processed: _Optional[int] = ..., file_counts: _Optional[_Union[FileCounts, _Mapping]] = ...) -> None: ...

class LocalInfo(_message.Message):
    __slots__ = ("version", "out_of_date")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    OUT_OF_DATE_FIELD_NUMBER: _ClassVar[int]
    version: str
    out_of_date: bool
    def __init__(self, version: _Optional[str] = ..., out_of_date: _Optional[bool] = ...) -> None: ...

class ShutdownRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class ShutdownResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AttachRequest(_message.Message):
    __slots__ = ("attach_id", "_info")
    ATTACH_ID_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    attach_id: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, attach_id: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class AttachResponse(_message.Message):
    __slots__ = ("run", "error")
    RUN_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    run: RunRecord
    error: ErrorInfo
    def __init__(self, run: _Optional[_Union[RunRecord, _Mapping]] = ..., error: _Optional[_Union[ErrorInfo, _Mapping]] = ...) -> None: ...

class TestInjectRequest(_message.Message):
    __slots__ = ("handler_exc", "handler_exit", "handler_abort", "sender_exc", "sender_exit", "sender_abort", "req_exc", "req_exit", "req_abort", "resp_exc", "resp_exit", "resp_abort", "msg_drop", "msg_hang", "_info")
    HANDLER_EXC_FIELD_NUMBER: _ClassVar[int]
    HANDLER_EXIT_FIELD_NUMBER: _ClassVar[int]
    HANDLER_ABORT_FIELD_NUMBER: _ClassVar[int]
    SENDER_EXC_FIELD_NUMBER: _ClassVar[int]
    SENDER_EXIT_FIELD_NUMBER: _ClassVar[int]
    SENDER_ABORT_FIELD_NUMBER: _ClassVar[int]
    REQ_EXC_FIELD_NUMBER: _ClassVar[int]
    REQ_EXIT_FIELD_NUMBER: _ClassVar[int]
    REQ_ABORT_FIELD_NUMBER: _ClassVar[int]
    RESP_EXC_FIELD_NUMBER: _ClassVar[int]
    RESP_EXIT_FIELD_NUMBER: _ClassVar[int]
    RESP_ABORT_FIELD_NUMBER: _ClassVar[int]
    MSG_DROP_FIELD_NUMBER: _ClassVar[int]
    MSG_HANG_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    handler_exc: bool
    handler_exit: bool
    handler_abort: bool
    sender_exc: bool
    sender_exit: bool
    sender_abort: bool
    req_exc: bool
    req_exit: bool
    req_abort: bool
    resp_exc: bool
    resp_exit: bool
    resp_abort: bool
    msg_drop: bool
    msg_hang: bool
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, handler_exc: _Optional[bool] = ..., handler_exit: _Optional[bool] = ..., handler_abort: _Optional[bool] = ..., sender_exc: _Optional[bool] = ..., sender_exit: _Optional[bool] = ..., sender_abort: _Optional[bool] = ..., req_exc: _Optional[bool] = ..., req_exit: _Optional[bool] = ..., req_abort: _Optional[bool] = ..., resp_exc: _Optional[bool] = ..., resp_exit: _Optional[bool] = ..., resp_abort: _Optional[bool] = ..., msg_drop: _Optional[bool] = ..., msg_hang: _Optional[bool] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class TestInjectResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HistoryAction(_message.Message):
    __slots__ = ("flush",)
    FLUSH_FIELD_NUMBER: _ClassVar[int]
    flush: bool
    def __init__(self, flush: _Optional[bool] = ...) -> None: ...

class PartialHistoryRequest(_message.Message):
    __slots__ = ("item", "step", "action", "_info")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[HistoryItem]
    step: HistoryStep
    action: HistoryAction
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, item: _Optional[_Iterable[_Union[HistoryItem, _Mapping]]] = ..., step: _Optional[_Union[HistoryStep, _Mapping]] = ..., action: _Optional[_Union[HistoryAction, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class PartialHistoryResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SampledHistoryRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class SampledHistoryItem(_message.Message):
    __slots__ = ("key", "nested_key", "values_float", "values_int")
    KEY_FIELD_NUMBER: _ClassVar[int]
    NESTED_KEY_FIELD_NUMBER: _ClassVar[int]
    VALUES_FLOAT_FIELD_NUMBER: _ClassVar[int]
    VALUES_INT_FIELD_NUMBER: _ClassVar[int]
    key: str
    nested_key: _containers.RepeatedScalarFieldContainer[str]
    values_float: _containers.RepeatedScalarFieldContainer[float]
    values_int: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, key: _Optional[str] = ..., nested_key: _Optional[_Iterable[str]] = ..., values_float: _Optional[_Iterable[float]] = ..., values_int: _Optional[_Iterable[int]] = ...) -> None: ...

class SampledHistoryResponse(_message.Message):
    __slots__ = ("item",)
    ITEM_FIELD_NUMBER: _ClassVar[int]
    item: _containers.RepeatedCompositeFieldContainer[SampledHistoryItem]
    def __init__(self, item: _Optional[_Iterable[_Union[SampledHistoryItem, _Mapping]]] = ...) -> None: ...

class RunStatusRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class RunStatusResponse(_message.Message):
    __slots__ = ("sync_items_total", "sync_items_pending", "sync_time")
    SYNC_ITEMS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    SYNC_ITEMS_PENDING_FIELD_NUMBER: _ClassVar[int]
    SYNC_TIME_FIELD_NUMBER: _ClassVar[int]
    sync_items_total: int
    sync_items_pending: int
    sync_time: _timestamp_pb2.Timestamp
    def __init__(self, sync_items_total: _Optional[int] = ..., sync_items_pending: _Optional[int] = ..., sync_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class RunStartRequest(_message.Message):
    __slots__ = ("run", "_info")
    RUN_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    run: RunRecord
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, run: _Optional[_Union[RunRecord, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class RunStartResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RunFinishWithoutExitRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class RunFinishWithoutExitResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CheckVersionRequest(_message.Message):
    __slots__ = ("current_version", "_info")
    CURRENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    current_version: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, current_version: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class CheckVersionResponse(_message.Message):
    __slots__ = ("upgrade_message", "yank_message", "delete_message")
    UPGRADE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    YANK_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DELETE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    upgrade_message: str
    yank_message: str
    delete_message: str
    def __init__(self, upgrade_message: _Optional[str] = ..., yank_message: _Optional[str] = ..., delete_message: _Optional[str] = ...) -> None: ...

class JobInfoRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class JobInfoResponse(_message.Message):
    __slots__ = ("sequenceId", "version")
    SEQUENCEID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    sequenceId: str
    version: str
    def __init__(self, sequenceId: _Optional[str] = ..., version: _Optional[str] = ...) -> None: ...

class LogArtifactRequest(_message.Message):
    __slots__ = ("artifact", "history_step", "staging_dir", "_info")
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    HISTORY_STEP_FIELD_NUMBER: _ClassVar[int]
    STAGING_DIR_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    artifact: ArtifactRecord
    history_step: int
    staging_dir: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, artifact: _Optional[_Union[ArtifactRecord, _Mapping]] = ..., history_step: _Optional[int] = ..., staging_dir: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class LogArtifactResponse(_message.Message):
    __slots__ = ("artifact_id", "error_message")
    ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    artifact_id: str
    error_message: str
    def __init__(self, artifact_id: _Optional[str] = ..., error_message: _Optional[str] = ...) -> None: ...

class DownloadArtifactRequest(_message.Message):
    __slots__ = ("artifact_id", "download_root", "allow_missing_references", "skip_cache", "path_prefix", "_info")
    ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_ROOT_FIELD_NUMBER: _ClassVar[int]
    ALLOW_MISSING_REFERENCES_FIELD_NUMBER: _ClassVar[int]
    SKIP_CACHE_FIELD_NUMBER: _ClassVar[int]
    PATH_PREFIX_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    artifact_id: str
    download_root: str
    allow_missing_references: bool
    skip_cache: bool
    path_prefix: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, artifact_id: _Optional[str] = ..., download_root: _Optional[str] = ..., allow_missing_references: _Optional[bool] = ..., skip_cache: _Optional[bool] = ..., path_prefix: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class DownloadArtifactResponse(_message.Message):
    __slots__ = ("error_message",)
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    error_message: str
    def __init__(self, error_message: _Optional[str] = ...) -> None: ...

class KeepaliveRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class KeepaliveResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ArtifactInfo(_message.Message):
    __slots__ = ("artifact", "entrypoint", "notebook", "build_context", "dockerfile")
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    ENTRYPOINT_FIELD_NUMBER: _ClassVar[int]
    NOTEBOOK_FIELD_NUMBER: _ClassVar[int]
    BUILD_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    DOCKERFILE_FIELD_NUMBER: _ClassVar[int]
    artifact: str
    entrypoint: _containers.RepeatedScalarFieldContainer[str]
    notebook: bool
    build_context: str
    dockerfile: str
    def __init__(self, artifact: _Optional[str] = ..., entrypoint: _Optional[_Iterable[str]] = ..., notebook: _Optional[bool] = ..., build_context: _Optional[str] = ..., dockerfile: _Optional[str] = ...) -> None: ...

class GitInfo(_message.Message):
    __slots__ = ("remote", "commit")
    REMOTE_FIELD_NUMBER: _ClassVar[int]
    COMMIT_FIELD_NUMBER: _ClassVar[int]
    remote: str
    commit: str
    def __init__(self, remote: _Optional[str] = ..., commit: _Optional[str] = ...) -> None: ...

class GitSource(_message.Message):
    __slots__ = ("git_info", "entrypoint", "notebook", "build_context", "dockerfile")
    GIT_INFO_FIELD_NUMBER: _ClassVar[int]
    ENTRYPOINT_FIELD_NUMBER: _ClassVar[int]
    NOTEBOOK_FIELD_NUMBER: _ClassVar[int]
    BUILD_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    DOCKERFILE_FIELD_NUMBER: _ClassVar[int]
    git_info: GitInfo
    entrypoint: _containers.RepeatedScalarFieldContainer[str]
    notebook: bool
    build_context: str
    dockerfile: str
    def __init__(self, git_info: _Optional[_Union[GitInfo, _Mapping]] = ..., entrypoint: _Optional[_Iterable[str]] = ..., notebook: _Optional[bool] = ..., build_context: _Optional[str] = ..., dockerfile: _Optional[str] = ...) -> None: ...

class ImageSource(_message.Message):
    __slots__ = ("image",)
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    image: str
    def __init__(self, image: _Optional[str] = ...) -> None: ...

class Source(_message.Message):
    __slots__ = ("git", "artifact", "image")
    GIT_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    git: GitSource
    artifact: ArtifactInfo
    image: ImageSource
    def __init__(self, git: _Optional[_Union[GitSource, _Mapping]] = ..., artifact: _Optional[_Union[ArtifactInfo, _Mapping]] = ..., image: _Optional[_Union[ImageSource, _Mapping]] = ...) -> None: ...

class JobSource(_message.Message):
    __slots__ = ("_version", "source_type", "source", "runtime")
    _VERSION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    _version: str
    source_type: str
    source: Source
    runtime: str
    def __init__(self, _version: _Optional[str] = ..., source_type: _Optional[str] = ..., source: _Optional[_Union[Source, _Mapping]] = ..., runtime: _Optional[str] = ...) -> None: ...

class PartialJobArtifact(_message.Message):
    __slots__ = ("job_name", "source_info")
    JOB_NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_INFO_FIELD_NUMBER: _ClassVar[int]
    job_name: str
    source_info: JobSource
    def __init__(self, job_name: _Optional[str] = ..., source_info: _Optional[_Union[JobSource, _Mapping]] = ...) -> None: ...

class UseArtifactRecord(_message.Message):
    __slots__ = ("id", "type", "name", "partial", "_info")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    name: str
    partial: PartialJobArtifact
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., name: _Optional[str] = ..., partial: _Optional[_Union[PartialJobArtifact, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class UseArtifactResult(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("cancel_slot", "_info")
    CANCEL_SLOT_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    cancel_slot: str
    _info: _wandb_base_pb2._RequestInfo
    def __init__(self, cancel_slot: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RequestInfo, _Mapping]] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ProbeSystemInfoRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DiskInfo(_message.Message):
    __slots__ = ("total", "used")
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    USED_FIELD_NUMBER: _ClassVar[int]
    total: int
    used: int
    def __init__(self, total: _Optional[int] = ..., used: _Optional[int] = ...) -> None: ...

class MemoryInfo(_message.Message):
    __slots__ = ("total",)
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    total: int
    def __init__(self, total: _Optional[int] = ...) -> None: ...

class CpuInfo(_message.Message):
    __slots__ = ("count", "count_logical")
    COUNT_FIELD_NUMBER: _ClassVar[int]
    COUNT_LOGICAL_FIELD_NUMBER: _ClassVar[int]
    count: int
    count_logical: int
    def __init__(self, count: _Optional[int] = ..., count_logical: _Optional[int] = ...) -> None: ...

class AppleInfo(_message.Message):
    __slots__ = ("name", "ecpu_cores", "pcpu_cores", "gpu_cores", "memory_gb", "swap_total_bytes", "ram_total_bytes", "mac_model")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ECPU_CORES_FIELD_NUMBER: _ClassVar[int]
    PCPU_CORES_FIELD_NUMBER: _ClassVar[int]
    GPU_CORES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_GB_FIELD_NUMBER: _ClassVar[int]
    SWAP_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    RAM_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAC_MODEL_FIELD_NUMBER: _ClassVar[int]
    name: str
    ecpu_cores: int
    pcpu_cores: int
    gpu_cores: int
    memory_gb: int
    swap_total_bytes: int
    ram_total_bytes: int
    mac_model: str
    def __init__(self, name: _Optional[str] = ..., ecpu_cores: _Optional[int] = ..., pcpu_cores: _Optional[int] = ..., gpu_cores: _Optional[int] = ..., memory_gb: _Optional[int] = ..., swap_total_bytes: _Optional[int] = ..., ram_total_bytes: _Optional[int] = ..., mac_model: _Optional[str] = ...) -> None: ...

class GpuNvidiaInfo(_message.Message):
    __slots__ = ("name", "memory_total", "cuda_cores", "architecture", "uuid")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TOTAL_FIELD_NUMBER: _ClassVar[int]
    CUDA_CORES_FIELD_NUMBER: _ClassVar[int]
    ARCHITECTURE_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    name: str
    memory_total: int
    cuda_cores: int
    architecture: str
    uuid: str
    def __init__(self, name: _Optional[str] = ..., memory_total: _Optional[int] = ..., cuda_cores: _Optional[int] = ..., architecture: _Optional[str] = ..., uuid: _Optional[str] = ...) -> None: ...

class GpuAmdInfo(_message.Message):
    __slots__ = ("id", "unique_id", "vbios_version", "performance_level", "gpu_overdrive", "gpu_memory_overdrive", "max_power", "series", "model", "vendor", "sku", "sclk_range", "mclk_range")
    ID_FIELD_NUMBER: _ClassVar[int]
    UNIQUE_ID_FIELD_NUMBER: _ClassVar[int]
    VBIOS_VERSION_FIELD_NUMBER: _ClassVar[int]
    PERFORMANCE_LEVEL_FIELD_NUMBER: _ClassVar[int]
    GPU_OVERDRIVE_FIELD_NUMBER: _ClassVar[int]
    GPU_MEMORY_OVERDRIVE_FIELD_NUMBER: _ClassVar[int]
    MAX_POWER_FIELD_NUMBER: _ClassVar[int]
    SERIES_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    SKU_FIELD_NUMBER: _ClassVar[int]
    SCLK_RANGE_FIELD_NUMBER: _ClassVar[int]
    MCLK_RANGE_FIELD_NUMBER: _ClassVar[int]
    id: str
    unique_id: str
    vbios_version: str
    performance_level: str
    gpu_overdrive: str
    gpu_memory_overdrive: str
    max_power: str
    series: str
    model: str
    vendor: str
    sku: str
    sclk_range: str
    mclk_range: str
    def __init__(self, id: _Optional[str] = ..., unique_id: _Optional[str] = ..., vbios_version: _Optional[str] = ..., performance_level: _Optional[str] = ..., gpu_overdrive: _Optional[str] = ..., gpu_memory_overdrive: _Optional[str] = ..., max_power: _Optional[str] = ..., series: _Optional[str] = ..., model: _Optional[str] = ..., vendor: _Optional[str] = ..., sku: _Optional[str] = ..., sclk_range: _Optional[str] = ..., mclk_range: _Optional[str] = ...) -> None: ...

class TrainiumInfo(_message.Message):
    __slots__ = ("name", "vendor", "neuron_device_count", "neuroncore_per_device_count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    NEURON_DEVICE_COUNT_FIELD_NUMBER: _ClassVar[int]
    NEURONCORE_PER_DEVICE_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    vendor: str
    neuron_device_count: int
    neuroncore_per_device_count: int
    def __init__(self, name: _Optional[str] = ..., vendor: _Optional[str] = ..., neuron_device_count: _Optional[int] = ..., neuroncore_per_device_count: _Optional[int] = ...) -> None: ...

class TPUInfo(_message.Message):
    __slots__ = ("name", "hbm_gib", "devices_per_chip", "count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    HBM_GIB_FIELD_NUMBER: _ClassVar[int]
    DEVICES_PER_CHIP_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    hbm_gib: int
    devices_per_chip: int
    count: int
    def __init__(self, name: _Optional[str] = ..., hbm_gib: _Optional[int] = ..., devices_per_chip: _Optional[int] = ..., count: _Optional[int] = ...) -> None: ...

class CoreWeaveInfo(_message.Message):
    __slots__ = ("cluster_name", "org_id", "region")
    CLUSTER_NAME_FIELD_NUMBER: _ClassVar[int]
    ORG_ID_FIELD_NUMBER: _ClassVar[int]
    REGION_FIELD_NUMBER: _ClassVar[int]
    cluster_name: str
    org_id: str
    region: str
    def __init__(self, cluster_name: _Optional[str] = ..., org_id: _Optional[str] = ..., region: _Optional[str] = ...) -> None: ...

class EnvironmentRecord(_message.Message):
    __slots__ = ("os", "python", "started_at", "docker", "args", "program", "code_path", "code_path_local", "git", "email", "root", "host", "username", "executable", "colab", "cpu_count", "cpu_count_logical", "gpu_type", "gpu_count", "disk", "memory", "cpu", "apple", "gpu_nvidia", "cuda_version", "gpu_amd", "slurm", "trainium", "tpu", "coreweave", "writer_id", "_info")
    class DiskEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: DiskInfo
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[DiskInfo, _Mapping]] = ...) -> None: ...
    class SlurmEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    OS_FIELD_NUMBER: _ClassVar[int]
    PYTHON_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    DOCKER_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    PROGRAM_FIELD_NUMBER: _ClassVar[int]
    CODE_PATH_FIELD_NUMBER: _ClassVar[int]
    CODE_PATH_LOCAL_FIELD_NUMBER: _ClassVar[int]
    GIT_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    EXECUTABLE_FIELD_NUMBER: _ClassVar[int]
    COLAB_FIELD_NUMBER: _ClassVar[int]
    CPU_COUNT_FIELD_NUMBER: _ClassVar[int]
    CPU_COUNT_LOGICAL_FIELD_NUMBER: _ClassVar[int]
    GPU_TYPE_FIELD_NUMBER: _ClassVar[int]
    GPU_COUNT_FIELD_NUMBER: _ClassVar[int]
    DISK_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FIELD_NUMBER: _ClassVar[int]
    CPU_FIELD_NUMBER: _ClassVar[int]
    APPLE_FIELD_NUMBER: _ClassVar[int]
    GPU_NVIDIA_FIELD_NUMBER: _ClassVar[int]
    CUDA_VERSION_FIELD_NUMBER: _ClassVar[int]
    GPU_AMD_FIELD_NUMBER: _ClassVar[int]
    SLURM_FIELD_NUMBER: _ClassVar[int]
    TRAINIUM_FIELD_NUMBER: _ClassVar[int]
    TPU_FIELD_NUMBER: _ClassVar[int]
    COREWEAVE_FIELD_NUMBER: _ClassVar[int]
    WRITER_ID_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    os: str
    python: str
    started_at: _timestamp_pb2.Timestamp
    docker: str
    args: _containers.RepeatedScalarFieldContainer[str]
    program: str
    code_path: str
    code_path_local: str
    git: GitRepoRecord
    email: str
    root: str
    host: str
    username: str
    executable: str
    colab: str
    cpu_count: int
    cpu_count_logical: int
    gpu_type: str
    gpu_count: int
    disk: _containers.MessageMap[str, DiskInfo]
    memory: MemoryInfo
    cpu: CpuInfo
    apple: AppleInfo
    gpu_nvidia: _containers.RepeatedCompositeFieldContainer[GpuNvidiaInfo]
    cuda_version: str
    gpu_amd: _containers.RepeatedCompositeFieldContainer[GpuAmdInfo]
    slurm: _containers.ScalarMap[str, str]
    trainium: TrainiumInfo
    tpu: TPUInfo
    coreweave: CoreWeaveInfo
    writer_id: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, os: _Optional[str] = ..., python: _Optional[str] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., docker: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., program: _Optional[str] = ..., code_path: _Optional[str] = ..., code_path_local: _Optional[str] = ..., git: _Optional[_Union[GitRepoRecord, _Mapping]] = ..., email: _Optional[str] = ..., root: _Optional[str] = ..., host: _Optional[str] = ..., username: _Optional[str] = ..., executable: _Optional[str] = ..., colab: _Optional[str] = ..., cpu_count: _Optional[int] = ..., cpu_count_logical: _Optional[int] = ..., gpu_type: _Optional[str] = ..., gpu_count: _Optional[int] = ..., disk: _Optional[_Mapping[str, DiskInfo]] = ..., memory: _Optional[_Union[MemoryInfo, _Mapping]] = ..., cpu: _Optional[_Union[CpuInfo, _Mapping]] = ..., apple: _Optional[_Union[AppleInfo, _Mapping]] = ..., gpu_nvidia: _Optional[_Iterable[_Union[GpuNvidiaInfo, _Mapping]]] = ..., cuda_version: _Optional[str] = ..., gpu_amd: _Optional[_Iterable[_Union[GpuAmdInfo, _Mapping]]] = ..., slurm: _Optional[_Mapping[str, str]] = ..., trainium: _Optional[_Union[TrainiumInfo, _Mapping]] = ..., tpu: _Optional[_Union[TPUInfo, _Mapping]] = ..., coreweave: _Optional[_Union[CoreWeaveInfo, _Mapping]] = ..., writer_id: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class PythonPackagesRequest(_message.Message):
    __slots__ = ("package",)
    class PythonPackage(_message.Message):
        __slots__ = ("name", "version")
        NAME_FIELD_NUMBER: _ClassVar[int]
        VERSION_FIELD_NUMBER: _ClassVar[int]
        name: str
        version: str
        def __init__(self, name: _Optional[str] = ..., version: _Optional[str] = ...) -> None: ...
    PACKAGE_FIELD_NUMBER: _ClassVar[int]
    package: _containers.RepeatedCompositeFieldContainer[PythonPackagesRequest.PythonPackage]
    def __init__(self, package: _Optional[_Iterable[_Union[PythonPackagesRequest.PythonPackage, _Mapping]]] = ...) -> None: ...

class JobInputPath(_message.Message):
    __slots__ = ("path",)
    PATH_FIELD_NUMBER: _ClassVar[int]
    path: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, path: _Optional[_Iterable[str]] = ...) -> None: ...

class JobInputSource(_message.Message):
    __slots__ = ("run_config", "file")
    class RunConfigSource(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class ConfigFileSource(_message.Message):
        __slots__ = ("path",)
        PATH_FIELD_NUMBER: _ClassVar[int]
        path: str
        def __init__(self, path: _Optional[str] = ...) -> None: ...
    RUN_CONFIG_FIELD_NUMBER: _ClassVar[int]
    FILE_FIELD_NUMBER: _ClassVar[int]
    run_config: JobInputSource.RunConfigSource
    file: JobInputSource.ConfigFileSource
    def __init__(self, run_config: _Optional[_Union[JobInputSource.RunConfigSource, _Mapping]] = ..., file: _Optional[_Union[JobInputSource.ConfigFileSource, _Mapping]] = ...) -> None: ...

class JobInputRequest(_message.Message):
    __slots__ = ("input_source", "include_paths", "exclude_paths", "input_schema")
    INPUT_SOURCE_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_PATHS_FIELD_NUMBER: _ClassVar[int]
    EXCLUDE_PATHS_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    input_source: JobInputSource
    include_paths: _containers.RepeatedCompositeFieldContainer[JobInputPath]
    exclude_paths: _containers.RepeatedCompositeFieldContainer[JobInputPath]
    input_schema: str
    def __init__(self, input_source: _Optional[_Union[JobInputSource, _Mapping]] = ..., include_paths: _Optional[_Iterable[_Union[JobInputPath, _Mapping]]] = ..., exclude_paths: _Optional[_Iterable[_Union[JobInputPath, _Mapping]]] = ..., input_schema: _Optional[str] = ...) -> None: ...
