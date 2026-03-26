from wandb.proto import wandb_api_pb2 as _wandb_api_pb2
from wandb.proto import wandb_base_pb2 as _wandb_base_pb2
from wandb.proto import wandb_internal_pb2 as _wandb_internal_pb2
from wandb.proto import wandb_settings_pb2 as _wandb_settings_pb2
from wandb.proto import wandb_sync_pb2 as _wandb_sync_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ServerAuthenticateRequest(_message.Message):
    __slots__ = ("api_key", "base_url", "_info")
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    api_key: str
    base_url: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, api_key: _Optional[str] = ..., base_url: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerAuthenticateResponse(_message.Message):
    __slots__ = ("default_entity", "error_status", "_info")
    DEFAULT_ENTITY_FIELD_NUMBER: _ClassVar[int]
    ERROR_STATUS_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    default_entity: str
    error_status: str
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, default_entity: _Optional[str] = ..., error_status: _Optional[str] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerShutdownRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerShutdownResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerStatusRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerStatusResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerInformInitRequest(_message.Message):
    __slots__ = ("settings", "_info")
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    settings: _wandb_settings_pb2.Settings
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformInitResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerInformFinishRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformFinishResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerInformAttachRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformAttachResponse(_message.Message):
    __slots__ = ("settings", "_info")
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    settings: _wandb_settings_pb2.Settings
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformDetachRequest(_message.Message):
    __slots__ = ("_info",)
    _INFO_FIELD_NUMBER: _ClassVar[int]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformDetachResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerInformTeardownRequest(_message.Message):
    __slots__ = ("exit_code", "_info")
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    exit_code: int
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, exit_code: _Optional[int] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class ServerInformTeardownResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerCancelRequest(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    def __init__(self, request_id: _Optional[str] = ...) -> None: ...

class ServerErrorResponse(_message.Message):
    __slots__ = ("message",)
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    message: str
    def __init__(self, message: _Optional[str] = ...) -> None: ...

class ServerRequest(_message.Message):
    __slots__ = ("request_id", "cancel", "record_publish", "record_communicate", "inform_init", "inform_finish", "inform_attach", "inform_detach", "inform_teardown", "authenticate", "init_sync", "sync", "sync_status", "api_init_request", "api_cleanup_request", "api_request")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    RECORD_PUBLISH_FIELD_NUMBER: _ClassVar[int]
    RECORD_COMMUNICATE_FIELD_NUMBER: _ClassVar[int]
    INFORM_INIT_FIELD_NUMBER: _ClassVar[int]
    INFORM_FINISH_FIELD_NUMBER: _ClassVar[int]
    INFORM_ATTACH_FIELD_NUMBER: _ClassVar[int]
    INFORM_DETACH_FIELD_NUMBER: _ClassVar[int]
    INFORM_TEARDOWN_FIELD_NUMBER: _ClassVar[int]
    AUTHENTICATE_FIELD_NUMBER: _ClassVar[int]
    INIT_SYNC_FIELD_NUMBER: _ClassVar[int]
    SYNC_FIELD_NUMBER: _ClassVar[int]
    SYNC_STATUS_FIELD_NUMBER: _ClassVar[int]
    API_INIT_REQUEST_FIELD_NUMBER: _ClassVar[int]
    API_CLEANUP_REQUEST_FIELD_NUMBER: _ClassVar[int]
    API_REQUEST_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    cancel: ServerCancelRequest
    record_publish: _wandb_internal_pb2.Record
    record_communicate: _wandb_internal_pb2.Record
    inform_init: ServerInformInitRequest
    inform_finish: ServerInformFinishRequest
    inform_attach: ServerInformAttachRequest
    inform_detach: ServerInformDetachRequest
    inform_teardown: ServerInformTeardownRequest
    authenticate: ServerAuthenticateRequest
    init_sync: _wandb_sync_pb2.ServerInitSyncRequest
    sync: _wandb_sync_pb2.ServerSyncRequest
    sync_status: _wandb_sync_pb2.ServerSyncStatusRequest
    api_init_request: _wandb_api_pb2.ServerApiInitRequest
    api_cleanup_request: _wandb_api_pb2.ServerApiCleanupRequest
    api_request: _wandb_api_pb2.ApiRequest
    def __init__(self, request_id: _Optional[str] = ..., cancel: _Optional[_Union[ServerCancelRequest, _Mapping]] = ..., record_publish: _Optional[_Union[_wandb_internal_pb2.Record, _Mapping]] = ..., record_communicate: _Optional[_Union[_wandb_internal_pb2.Record, _Mapping]] = ..., inform_init: _Optional[_Union[ServerInformInitRequest, _Mapping]] = ..., inform_finish: _Optional[_Union[ServerInformFinishRequest, _Mapping]] = ..., inform_attach: _Optional[_Union[ServerInformAttachRequest, _Mapping]] = ..., inform_detach: _Optional[_Union[ServerInformDetachRequest, _Mapping]] = ..., inform_teardown: _Optional[_Union[ServerInformTeardownRequest, _Mapping]] = ..., authenticate: _Optional[_Union[ServerAuthenticateRequest, _Mapping]] = ..., init_sync: _Optional[_Union[_wandb_sync_pb2.ServerInitSyncRequest, _Mapping]] = ..., sync: _Optional[_Union[_wandb_sync_pb2.ServerSyncRequest, _Mapping]] = ..., sync_status: _Optional[_Union[_wandb_sync_pb2.ServerSyncStatusRequest, _Mapping]] = ..., api_init_request: _Optional[_Union[_wandb_api_pb2.ServerApiInitRequest, _Mapping]] = ..., api_cleanup_request: _Optional[_Union[_wandb_api_pb2.ServerApiCleanupRequest, _Mapping]] = ..., api_request: _Optional[_Union[_wandb_api_pb2.ApiRequest, _Mapping]] = ...) -> None: ...

class ServerResponse(_message.Message):
    __slots__ = ("request_id", "result_communicate", "inform_init_response", "inform_finish_response", "inform_attach_response", "inform_detach_response", "inform_teardown_response", "authenticate_response", "init_sync_response", "sync_response", "sync_status_response", "api_init_response", "api_response", "error_response")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_COMMUNICATE_FIELD_NUMBER: _ClassVar[int]
    INFORM_INIT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INFORM_FINISH_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INFORM_ATTACH_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INFORM_DETACH_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INFORM_TEARDOWN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    AUTHENTICATE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    INIT_SYNC_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SYNC_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    SYNC_STATUS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    API_INIT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    API_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ERROR_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    result_communicate: _wandb_internal_pb2.Result
    inform_init_response: ServerInformInitResponse
    inform_finish_response: ServerInformFinishResponse
    inform_attach_response: ServerInformAttachResponse
    inform_detach_response: ServerInformDetachResponse
    inform_teardown_response: ServerInformTeardownResponse
    authenticate_response: ServerAuthenticateResponse
    init_sync_response: _wandb_sync_pb2.ServerInitSyncResponse
    sync_response: _wandb_sync_pb2.ServerSyncResponse
    sync_status_response: _wandb_sync_pb2.ServerSyncStatusResponse
    api_init_response: _wandb_api_pb2.ServerApiInitResponse
    api_response: _wandb_api_pb2.ApiResponse
    error_response: ServerErrorResponse
    def __init__(self, request_id: _Optional[str] = ..., result_communicate: _Optional[_Union[_wandb_internal_pb2.Result, _Mapping]] = ..., inform_init_response: _Optional[_Union[ServerInformInitResponse, _Mapping]] = ..., inform_finish_response: _Optional[_Union[ServerInformFinishResponse, _Mapping]] = ..., inform_attach_response: _Optional[_Union[ServerInformAttachResponse, _Mapping]] = ..., inform_detach_response: _Optional[_Union[ServerInformDetachResponse, _Mapping]] = ..., inform_teardown_response: _Optional[_Union[ServerInformTeardownResponse, _Mapping]] = ..., authenticate_response: _Optional[_Union[ServerAuthenticateResponse, _Mapping]] = ..., init_sync_response: _Optional[_Union[_wandb_sync_pb2.ServerInitSyncResponse, _Mapping]] = ..., sync_response: _Optional[_Union[_wandb_sync_pb2.ServerSyncResponse, _Mapping]] = ..., sync_status_response: _Optional[_Union[_wandb_sync_pb2.ServerSyncStatusResponse, _Mapping]] = ..., api_init_response: _Optional[_Union[_wandb_api_pb2.ServerApiInitResponse, _Mapping]] = ..., api_response: _Optional[_Union[_wandb_api_pb2.ApiResponse, _Mapping]] = ..., error_response: _Optional[_Union[ServerErrorResponse, _Mapping]] = ...) -> None: ...
