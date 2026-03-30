from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class _RecordInfo(_message.Message):
    __slots__ = ("stream_id", "_tracelog_id")
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    _TRACELOG_ID_FIELD_NUMBER: _ClassVar[int]
    stream_id: str
    _tracelog_id: str
    def __init__(self, stream_id: _Optional[str] = ..., _tracelog_id: _Optional[str] = ...) -> None: ...

class _RequestInfo(_message.Message):
    __slots__ = ("stream_id",)
    STREAM_ID_FIELD_NUMBER: _ClassVar[int]
    stream_id: str
    def __init__(self, stream_id: _Optional[str] = ...) -> None: ...

class _ResultInfo(_message.Message):
    __slots__ = ("_tracelog_id",)
    _TRACELOG_ID_FIELD_NUMBER: _ClassVar[int]
    _tracelog_id: str
    def __init__(self, _tracelog_id: _Optional[str] = ...) -> None: ...
