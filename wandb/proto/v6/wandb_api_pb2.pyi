from wandb.proto import wandb_internal_pb2 as _wandb_internal_pb2
from wandb.proto import wandb_settings_pb2 as _wandb_settings_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ErrorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UNKNOWN_ERROR: _ClassVar[ErrorType]
    INCOMPLETE_RUN_HISTORY_ERROR: _ClassVar[ErrorType]
UNKNOWN_ERROR: ErrorType
INCOMPLETE_RUN_HISTORY_ERROR: ErrorType

class ServerApiInitRequest(_message.Message):
    __slots__ = ("settings",)
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    settings: _wandb_settings_pb2.Settings
    def __init__(self, settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ...) -> None: ...

class ServerApiInitResponse(_message.Message):
    __slots__ = ("error_message", "api_id")
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    API_ID_FIELD_NUMBER: _ClassVar[int]
    error_message: str
    api_id: str
    def __init__(self, error_message: _Optional[str] = ..., api_id: _Optional[str] = ...) -> None: ...

class ApiRequest(_message.Message):
    __slots__ = ("api_id", "read_run_history_request", "features_request")
    API_ID_FIELD_NUMBER: _ClassVar[int]
    READ_RUN_HISTORY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    FEATURES_REQUEST_FIELD_NUMBER: _ClassVar[int]
    api_id: str
    read_run_history_request: ReadRunHistoryRequest
    features_request: FeaturesRequest
    def __init__(self, api_id: _Optional[str] = ..., read_run_history_request: _Optional[_Union[ReadRunHistoryRequest, _Mapping]] = ..., features_request: _Optional[_Union[FeaturesRequest, _Mapping]] = ...) -> None: ...

class ApiResponse(_message.Message):
    __slots__ = ("read_run_history_response", "features_response", "api_error_response")
    READ_RUN_HISTORY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    FEATURES_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    API_ERROR_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    read_run_history_response: ReadRunHistoryResponse
    features_response: FeaturesResponse
    api_error_response: ApiErrorResponse
    def __init__(self, read_run_history_response: _Optional[_Union[ReadRunHistoryResponse, _Mapping]] = ..., features_response: _Optional[_Union[FeaturesResponse, _Mapping]] = ..., api_error_response: _Optional[_Union[ApiErrorResponse, _Mapping]] = ...) -> None: ...

class ApiErrorResponse(_message.Message):
    __slots__ = ("message", "error_type")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_TYPE_FIELD_NUMBER: _ClassVar[int]
    message: str
    error_type: ErrorType
    def __init__(self, message: _Optional[str] = ..., error_type: _Optional[_Union[ErrorType, str]] = ...) -> None: ...

class ServerApiCleanupRequest(_message.Message):
    __slots__ = ("api_id",)
    API_ID_FIELD_NUMBER: _ClassVar[int]
    api_id: str
    def __init__(self, api_id: _Optional[str] = ...) -> None: ...

class FeaturesRequest(_message.Message):
    __slots__ = ("features",)
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    features: _containers.RepeatedScalarFieldContainer[_wandb_internal_pb2.ServerFeature]
    def __init__(self, features: _Optional[_Iterable[_Union[_wandb_internal_pb2.ServerFeature, str]]] = ...) -> None: ...

class FeaturesResponse(_message.Message):
    __slots__ = ("enabled",)
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    enabled: _containers.RepeatedScalarFieldContainer[_wandb_internal_pb2.ServerFeature]
    def __init__(self, enabled: _Optional[_Iterable[_Union[_wandb_internal_pb2.ServerFeature, str]]] = ...) -> None: ...

class ReadRunHistoryRequest(_message.Message):
    __slots__ = ("scan_run_history_init", "scan_run_history", "scan_run_history_cleanup", "download_run_history_init", "download_run_history", "download_run_history_status")
    SCAN_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_CLEANUP_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_STATUS_FIELD_NUMBER: _ClassVar[int]
    scan_run_history_init: ScanRunHistoryInit
    scan_run_history: ScanRunHistory
    scan_run_history_cleanup: ScanRunHistoryCleanup
    download_run_history_init: DownloadRunHistoryInit
    download_run_history: DownloadRunHistory
    download_run_history_status: DownloadRunHistoryStatus
    def __init__(self, scan_run_history_init: _Optional[_Union[ScanRunHistoryInit, _Mapping]] = ..., scan_run_history: _Optional[_Union[ScanRunHistory, _Mapping]] = ..., scan_run_history_cleanup: _Optional[_Union[ScanRunHistoryCleanup, _Mapping]] = ..., download_run_history_init: _Optional[_Union[DownloadRunHistoryInit, _Mapping]] = ..., download_run_history: _Optional[_Union[DownloadRunHistory, _Mapping]] = ..., download_run_history_status: _Optional[_Union[DownloadRunHistoryStatus, _Mapping]] = ...) -> None: ...

class ReadRunHistoryResponse(_message.Message):
    __slots__ = ("scan_run_history_init", "run_history", "scan_run_history_cleanup", "download_run_history_init", "download_run_history", "download_run_history_status")
    SCAN_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_CLEANUP_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_STATUS_FIELD_NUMBER: _ClassVar[int]
    scan_run_history_init: ScanRunHistoryInitResponse
    run_history: RunHistoryResponse
    scan_run_history_cleanup: ScanRunHistoryCleanupResponse
    download_run_history_init: DownloadRunHistoryInitResponse
    download_run_history: DownloadRunHistoryResponse
    download_run_history_status: DownloadRunHistoryStatusResponse
    def __init__(self, scan_run_history_init: _Optional[_Union[ScanRunHistoryInitResponse, _Mapping]] = ..., run_history: _Optional[_Union[RunHistoryResponse, _Mapping]] = ..., scan_run_history_cleanup: _Optional[_Union[ScanRunHistoryCleanupResponse, _Mapping]] = ..., download_run_history_init: _Optional[_Union[DownloadRunHistoryInitResponse, _Mapping]] = ..., download_run_history: _Optional[_Union[DownloadRunHistoryResponse, _Mapping]] = ..., download_run_history_status: _Optional[_Union[DownloadRunHistoryStatusResponse, _Mapping]] = ...) -> None: ...

class ScanRunHistoryInit(_message.Message):
    __slots__ = ("entity", "project", "run_id", "keys", "use_cache")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    KEYS_FIELD_NUMBER: _ClassVar[int]
    USE_CACHE_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    keys: _containers.RepeatedScalarFieldContainer[str]
    use_cache: bool
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., keys: _Optional[_Iterable[str]] = ..., use_cache: bool = ...) -> None: ...

class ScanRunHistoryInitResponse(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class ScanRunHistory(_message.Message):
    __slots__ = ("min_step", "max_step", "request_id")
    MIN_STEP_FIELD_NUMBER: _ClassVar[int]
    MAX_STEP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    min_step: int
    max_step: int
    request_id: int
    def __init__(self, min_step: _Optional[int] = ..., max_step: _Optional[int] = ..., request_id: _Optional[int] = ...) -> None: ...

class RunHistoryResponse(_message.Message):
    __slots__ = ("history_rows",)
    HISTORY_ROWS_FIELD_NUMBER: _ClassVar[int]
    history_rows: _containers.RepeatedCompositeFieldContainer[HistoryRow]
    def __init__(self, history_rows: _Optional[_Iterable[_Union[HistoryRow, _Mapping]]] = ...) -> None: ...

class HistoryRow(_message.Message):
    __slots__ = ("history_items",)
    HISTORY_ITEMS_FIELD_NUMBER: _ClassVar[int]
    history_items: _containers.RepeatedCompositeFieldContainer[ParquetHistoryItem]
    def __init__(self, history_items: _Optional[_Iterable[_Union[ParquetHistoryItem, _Mapping]]] = ...) -> None: ...

class ParquetHistoryItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class ScanRunHistoryCleanup(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class ScanRunHistoryCleanupResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DownloadRunHistoryInit(_message.Message):
    __slots__ = ("entity", "project", "run_id", "download_dir", "require_complete_history")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_DIR_FIELD_NUMBER: _ClassVar[int]
    REQUIRE_COMPLETE_HISTORY_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    download_dir: str
    require_complete_history: bool
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., download_dir: _Optional[str] = ..., require_complete_history: bool = ...) -> None: ...

class DownloadRunHistoryInitResponse(_message.Message):
    __slots__ = ("request_id", "contains_live_data")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CONTAINS_LIVE_DATA_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    contains_live_data: bool
    def __init__(self, request_id: _Optional[int] = ..., contains_live_data: bool = ...) -> None: ...

class DownloadRunHistory(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class DownloadRunHistoryResponse(_message.Message):
    __slots__ = ("downloaded_files", "errors")
    class ErrorsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DOWNLOADED_FILES_FIELD_NUMBER: _ClassVar[int]
    ERRORS_FIELD_NUMBER: _ClassVar[int]
    downloaded_files: _containers.RepeatedScalarFieldContainer[str]
    errors: _containers.ScalarMap[str, str]
    def __init__(self, downloaded_files: _Optional[_Iterable[str]] = ..., errors: _Optional[_Mapping[str, str]] = ...) -> None: ...

class IncompleteRunHistoryError(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DownloadRunHistoryStatus(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class DownloadRunHistoryStatusResponse(_message.Message):
    __slots__ = ("operation_stats",)
    OPERATION_STATS_FIELD_NUMBER: _ClassVar[int]
    operation_stats: _wandb_internal_pb2.OperationStats
    def __init__(self, operation_stats: _Optional[_Union[_wandb_internal_pb2.OperationStats, _Mapping]] = ...) -> None: ...
