from wandb.proto import wandb_internal_pb2 as _wandb_internal_pb2
from wandb.proto import wandb_settings_pb2 as _wandb_settings_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ServerInitSyncRequest(_message.Message):
    __slots__ = ("path", "cwd", "live", "settings", "new_entity", "new_project", "new_run_id", "new_job_type", "tag_replacements")
    class TagReplacementsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PATH_FIELD_NUMBER: _ClassVar[int]
    CWD_FIELD_NUMBER: _ClassVar[int]
    LIVE_FIELD_NUMBER: _ClassVar[int]
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    NEW_ENTITY_FIELD_NUMBER: _ClassVar[int]
    NEW_PROJECT_FIELD_NUMBER: _ClassVar[int]
    NEW_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_JOB_TYPE_FIELD_NUMBER: _ClassVar[int]
    TAG_REPLACEMENTS_FIELD_NUMBER: _ClassVar[int]
    path: _containers.RepeatedScalarFieldContainer[str]
    cwd: str
    live: bool
    settings: _wandb_settings_pb2.Settings
    new_entity: str
    new_project: str
    new_run_id: str
    new_job_type: str
    tag_replacements: _containers.ScalarMap[str, str]
    def __init__(self, path: _Optional[_Iterable[str]] = ..., cwd: _Optional[str] = ..., live: _Optional[bool] = ..., settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ..., new_entity: _Optional[str] = ..., new_project: _Optional[str] = ..., new_run_id: _Optional[str] = ..., new_job_type: _Optional[str] = ..., tag_replacements: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ServerInitSyncResponse(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class ServerSyncRequest(_message.Message):
    __slots__ = ("id", "parallelism")
    ID_FIELD_NUMBER: _ClassVar[int]
    PARALLELISM_FIELD_NUMBER: _ClassVar[int]
    id: str
    parallelism: int
    def __init__(self, id: _Optional[str] = ..., parallelism: _Optional[int] = ...) -> None: ...

class ServerSyncResponse(_message.Message):
    __slots__ = ("messages",)
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    messages: _containers.RepeatedCompositeFieldContainer[ServerSyncMessage]
    def __init__(self, messages: _Optional[_Iterable[_Union[ServerSyncMessage, _Mapping]]] = ...) -> None: ...

class ServerSyncStatusRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class ServerSyncStatusResponse(_message.Message):
    __slots__ = ("stats", "new_messages")
    STATS_FIELD_NUMBER: _ClassVar[int]
    NEW_MESSAGES_FIELD_NUMBER: _ClassVar[int]
    stats: _containers.RepeatedCompositeFieldContainer[_wandb_internal_pb2.OperationStats]
    new_messages: _containers.RepeatedCompositeFieldContainer[ServerSyncMessage]
    def __init__(self, stats: _Optional[_Iterable[_Union[_wandb_internal_pb2.OperationStats, _Mapping]]] = ..., new_messages: _Optional[_Iterable[_Union[ServerSyncMessage, _Mapping]]] = ...) -> None: ...

class ServerSyncMessage(_message.Message):
    __slots__ = ("severity", "content")
    class Severity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SEVERITY_NOTSET: _ClassVar[ServerSyncMessage.Severity]
        SEVERITY_INFO: _ClassVar[ServerSyncMessage.Severity]
        SEVERITY_WARNING: _ClassVar[ServerSyncMessage.Severity]
        SEVERITY_ERROR: _ClassVar[ServerSyncMessage.Severity]
    SEVERITY_NOTSET: ServerSyncMessage.Severity
    SEVERITY_INFO: ServerSyncMessage.Severity
    SEVERITY_WARNING: ServerSyncMessage.Severity
    SEVERITY_ERROR: ServerSyncMessage.Severity
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    severity: ServerSyncMessage.Severity
    content: str
    def __init__(self, severity: _Optional[_Union[ServerSyncMessage.Severity, str]] = ..., content: _Optional[str] = ...) -> None: ...
