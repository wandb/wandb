from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OpenTelemetryRequest(_message.Message):
    __slots__ = ("open_telemetry_log_request", "open_telemetry_counter_request")
    OPEN_TELEMETRY_LOG_REQUEST_FIELD_NUMBER: _ClassVar[int]
    OPEN_TELEMETRY_COUNTER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    open_telemetry_log_request: OpenTelemetryLogRequest
    open_telemetry_counter_request: OpenTelemetryCounterRequest
    def __init__(self, open_telemetry_log_request: _Optional[_Union[OpenTelemetryLogRequest, _Mapping]] = ..., open_telemetry_counter_request: _Optional[_Union[OpenTelemetryCounterRequest, _Mapping]] = ...) -> None: ...

class OpenTelemetryLogRequest(_message.Message):
    __slots__ = ("message", "attributes", "severity")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    message: str
    attributes: _containers.ScalarMap[str, str]
    severity: int
    def __init__(self, message: _Optional[str] = ..., attributes: _Optional[_Mapping[str, str]] = ..., severity: _Optional[int] = ...) -> None: ...

class OpenTelemetryCounterRequest(_message.Message):
    __slots__ = ("name", "low_cardinality_attributes")
    NAME_FIELD_NUMBER: _ClassVar[int]
    LOW_CARDINALITY_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    name: str
    low_cardinality_attributes: LowCardinalityAttributes
    def __init__(self, name: _Optional[str] = ..., low_cardinality_attributes: _Optional[_Union[LowCardinalityAttributes, _Mapping]] = ...) -> None: ...

class LowCardinalityAttributes(_message.Message):
    __slots__ = ("python_version", "python_runtime", "wandb_version", "exception_type")
    PYTHON_VERSION_FIELD_NUMBER: _ClassVar[int]
    PYTHON_RUNTIME_FIELD_NUMBER: _ClassVar[int]
    WANDB_VERSION_FIELD_NUMBER: _ClassVar[int]
    EXCEPTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    python_version: str
    python_runtime: str
    wandb_version: str
    exception_type: str
    def __init__(self, python_version: _Optional[str] = ..., python_runtime: _Optional[str] = ..., wandb_version: _Optional[str] = ..., exception_type: _Optional[str] = ...) -> None: ...
