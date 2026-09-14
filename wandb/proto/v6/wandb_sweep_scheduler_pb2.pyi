from wandb.proto import wandb_settings_pb2 as _wandb_settings_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SweepRunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SWEEP_RUN_STATE_UNSPECIFIED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_RUNNING: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_PENDING: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_PREEMPTING: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_PREEMPTED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_FINISHED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_FAILED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_CRASHED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_KILLED: _ClassVar[SweepRunState]
    SWEEP_RUN_STATE_UNKNOWN: _ClassVar[SweepRunState]
SWEEP_RUN_STATE_UNSPECIFIED: SweepRunState
SWEEP_RUN_STATE_RUNNING: SweepRunState
SWEEP_RUN_STATE_PENDING: SweepRunState
SWEEP_RUN_STATE_PREEMPTING: SweepRunState
SWEEP_RUN_STATE_PREEMPTED: SweepRunState
SWEEP_RUN_STATE_FINISHED: SweepRunState
SWEEP_RUN_STATE_FAILED: SweepRunState
SWEEP_RUN_STATE_CRASHED: SweepRunState
SWEEP_RUN_STATE_KILLED: SweepRunState
SWEEP_RUN_STATE_UNKNOWN: SweepRunState

class SweepSchedulerClientInitRequest(_message.Message):
    __slots__ = ("entity", "project", "sweep_id", "settings", "batch_size", "poll_interval_seconds")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    SWEEP_ID_FIELD_NUMBER: _ClassVar[int]
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    POLL_INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    sweep_id: str
    settings: _wandb_settings_pb2.Settings
    batch_size: int
    poll_interval_seconds: float
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., sweep_id: _Optional[str] = ..., settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ..., batch_size: _Optional[int] = ..., poll_interval_seconds: _Optional[float] = ...) -> None: ...

class SweepSchedulerServerInitResponse(_message.Message):
    __slots__ = ("session_id", "sweep_config", "display_name", "controller_run_name")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SWEEP_CONFIG_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_RUN_NAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    sweep_config: str
    display_name: str
    controller_run_name: str
    def __init__(self, session_id: _Optional[str] = ..., sweep_config: _Optional[str] = ..., display_name: _Optional[str] = ..., controller_run_name: _Optional[str] = ...) -> None: ...

class SweepSchedulerClientNextTaskRequest(_message.Message):
    __slots__ = ("session_id", "result")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    result: SweepSchedulerClientTaskResult
    def __init__(self, session_id: _Optional[str] = ..., result: _Optional[_Union[SweepSchedulerClientTaskResult, _Mapping]] = ...) -> None: ...

class SweepSchedulerServerNextTaskResponse(_message.Message):
    __slots__ = ("task_seq", "warm_start", "generation", "done")
    TASK_SEQ_FIELD_NUMBER: _ClassVar[int]
    WARM_START_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    task_seq: int
    warm_start: SweepSchedulerServerWarmStartTask
    generation: SweepSchedulerServerGenerationTask
    done: SweepSchedulerServerDoneTask
    def __init__(self, task_seq: _Optional[int] = ..., warm_start: _Optional[_Union[SweepSchedulerServerWarmStartTask, _Mapping]] = ..., generation: _Optional[_Union[SweepSchedulerServerGenerationTask, _Mapping]] = ..., done: _Optional[_Union[SweepSchedulerServerDoneTask, _Mapping]] = ...) -> None: ...

class SweepSchedulerClientStopRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class SweepSchedulerServerWarmStartTask(_message.Message):
    __slots__ = ("finished_runs", "active_runs", "has_more")
    FINISHED_RUNS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_RUNS_FIELD_NUMBER: _ClassVar[int]
    HAS_MORE_FIELD_NUMBER: _ClassVar[int]
    finished_runs: _containers.RepeatedCompositeFieldContainer[SweepSchedulerServerRunData]
    active_runs: _containers.RepeatedCompositeFieldContainer[SweepSchedulerServerRunData]
    has_more: bool
    def __init__(self, finished_runs: _Optional[_Iterable[_Union[SweepSchedulerServerRunData, _Mapping]]] = ..., active_runs: _Optional[_Iterable[_Union[SweepSchedulerServerRunData, _Mapping]]] = ..., has_more: bool = ...) -> None: ...

class SweepSchedulerServerGenerationTask(_message.Message):
    __slots__ = ("updates", "ask_up_to", "prune_candidates", "discarded_optimizer_run_ids")
    UPDATES_FIELD_NUMBER: _ClassVar[int]
    ASK_UP_TO_FIELD_NUMBER: _ClassVar[int]
    PRUNE_CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    DISCARDED_OPTIMIZER_RUN_IDS_FIELD_NUMBER: _ClassVar[int]
    updates: _containers.RepeatedCompositeFieldContainer[SweepSchedulerServerRunUpdate]
    ask_up_to: int
    prune_candidates: _containers.RepeatedScalarFieldContainer[str]
    discarded_optimizer_run_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, updates: _Optional[_Iterable[_Union[SweepSchedulerServerRunUpdate, _Mapping]]] = ..., ask_up_to: _Optional[int] = ..., prune_candidates: _Optional[_Iterable[str]] = ..., discarded_optimizer_run_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class SweepSchedulerServerRunUpdate(_message.Message):
    __slots__ = ("run", "pruned")
    RUN_FIELD_NUMBER: _ClassVar[int]
    PRUNED_FIELD_NUMBER: _ClassVar[int]
    run: SweepSchedulerServerRunData
    pruned: bool
    def __init__(self, run: _Optional[_Union[SweepSchedulerServerRunData, _Mapping]] = ..., pruned: bool = ...) -> None: ...

class SweepSchedulerServerRunData(_message.Message):
    __slots__ = ("wandb_run_id", "optimizer_run_id", "state", "config_json", "summary_json", "history_json")
    WANDB_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZER_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_JSON_FIELD_NUMBER: _ClassVar[int]
    HISTORY_JSON_FIELD_NUMBER: _ClassVar[int]
    wandb_run_id: str
    optimizer_run_id: str
    state: SweepRunState
    config_json: str
    summary_json: str
    history_json: str
    def __init__(self, wandb_run_id: _Optional[str] = ..., optimizer_run_id: _Optional[str] = ..., state: _Optional[_Union[SweepRunState, str]] = ..., config_json: _Optional[str] = ..., summary_json: _Optional[str] = ..., history_json: _Optional[str] = ...) -> None: ...

class SweepSchedulerServerDoneTask(_message.Message):
    __slots__ = ("reason", "message", "discarded_optimizer_run_ids")
    class Reason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        REASON_UNSPECIFIED: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_EXHAUSTED: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_TERMINATED: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_SWEEP_FINISHED: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_SWEEP_NOT_FOUND: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_FATAL_ERROR: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_OPTIMIZER_ERROR: _ClassVar[SweepSchedulerServerDoneTask.Reason]
        REASON_SHUTDOWN: _ClassVar[SweepSchedulerServerDoneTask.Reason]
    REASON_UNSPECIFIED: SweepSchedulerServerDoneTask.Reason
    REASON_EXHAUSTED: SweepSchedulerServerDoneTask.Reason
    REASON_TERMINATED: SweepSchedulerServerDoneTask.Reason
    REASON_SWEEP_FINISHED: SweepSchedulerServerDoneTask.Reason
    REASON_SWEEP_NOT_FOUND: SweepSchedulerServerDoneTask.Reason
    REASON_FATAL_ERROR: SweepSchedulerServerDoneTask.Reason
    REASON_OPTIMIZER_ERROR: SweepSchedulerServerDoneTask.Reason
    REASON_SHUTDOWN: SweepSchedulerServerDoneTask.Reason
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DISCARDED_OPTIMIZER_RUN_IDS_FIELD_NUMBER: _ClassVar[int]
    reason: SweepSchedulerServerDoneTask.Reason
    message: str
    discarded_optimizer_run_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, reason: _Optional[_Union[SweepSchedulerServerDoneTask.Reason, str]] = ..., message: _Optional[str] = ..., discarded_optimizer_run_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class SweepSchedulerClientTaskResult(_message.Message):
    __slots__ = ("task_seq", "warm_start", "generation", "error")
    TASK_SEQ_FIELD_NUMBER: _ClassVar[int]
    WARM_START_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    task_seq: int
    warm_start: SweepSchedulerClientWarmStartResult
    generation: SweepSchedulerClientGenerationResult
    error: SweepSchedulerClientTaskError
    def __init__(self, task_seq: _Optional[int] = ..., warm_start: _Optional[_Union[SweepSchedulerClientWarmStartResult, _Mapping]] = ..., generation: _Optional[_Union[SweepSchedulerClientGenerationResult, _Mapping]] = ..., error: _Optional[_Union[SweepSchedulerClientTaskError, _Mapping]] = ...) -> None: ...

class SweepSchedulerClientWarmStartResult(_message.Message):
    __slots__ = ("adoptions", "skipped")
    class AdoptionsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ADOPTIONS_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    adoptions: _containers.ScalarMap[str, str]
    skipped: _containers.RepeatedCompositeFieldContainer[SweepSchedulerClientSkippedRun]
    def __init__(self, adoptions: _Optional[_Mapping[str, str]] = ..., skipped: _Optional[_Iterable[_Union[SweepSchedulerClientSkippedRun, _Mapping]]] = ...) -> None: ...

class SweepSchedulerClientSkippedRun(_message.Message):
    __slots__ = ("wandb_run_id", "error")
    WANDB_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    wandb_run_id: str
    error: str
    def __init__(self, wandb_run_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SweepSchedulerClientGenerationResult(_message.Message):
    __slots__ = ("ask_outcome", "suggestions", "prune", "terminate", "tell_errors")
    class AskOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ASK_OUTCOME_UNSPECIFIED: _ClassVar[SweepSchedulerClientGenerationResult.AskOutcome]
        ASK_OUTCOME_SUGGESTED: _ClassVar[SweepSchedulerClientGenerationResult.AskOutcome]
        ASK_OUTCOME_DECLINED: _ClassVar[SweepSchedulerClientGenerationResult.AskOutcome]
        ASK_OUTCOME_EXHAUSTED: _ClassVar[SweepSchedulerClientGenerationResult.AskOutcome]
    ASK_OUTCOME_UNSPECIFIED: SweepSchedulerClientGenerationResult.AskOutcome
    ASK_OUTCOME_SUGGESTED: SweepSchedulerClientGenerationResult.AskOutcome
    ASK_OUTCOME_DECLINED: SweepSchedulerClientGenerationResult.AskOutcome
    ASK_OUTCOME_EXHAUSTED: SweepSchedulerClientGenerationResult.AskOutcome
    ASK_OUTCOME_FIELD_NUMBER: _ClassVar[int]
    SUGGESTIONS_FIELD_NUMBER: _ClassVar[int]
    PRUNE_FIELD_NUMBER: _ClassVar[int]
    TERMINATE_FIELD_NUMBER: _ClassVar[int]
    TELL_ERRORS_FIELD_NUMBER: _ClassVar[int]
    ask_outcome: SweepSchedulerClientGenerationResult.AskOutcome
    suggestions: _containers.RepeatedCompositeFieldContainer[SweepSchedulerClientRunSuggestion]
    prune: _containers.RepeatedScalarFieldContainer[str]
    terminate: bool
    tell_errors: _containers.RepeatedCompositeFieldContainer[SweepSchedulerClientTellError]
    def __init__(self, ask_outcome: _Optional[_Union[SweepSchedulerClientGenerationResult.AskOutcome, str]] = ..., suggestions: _Optional[_Iterable[_Union[SweepSchedulerClientRunSuggestion, _Mapping]]] = ..., prune: _Optional[_Iterable[str]] = ..., terminate: bool = ..., tell_errors: _Optional[_Iterable[_Union[SweepSchedulerClientTellError, _Mapping]]] = ...) -> None: ...

class SweepSchedulerClientRunSuggestion(_message.Message):
    __slots__ = ("optimizer_run_id", "config_json")
    OPTIMIZER_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    optimizer_run_id: str
    config_json: str
    def __init__(self, optimizer_run_id: _Optional[str] = ..., config_json: _Optional[str] = ...) -> None: ...

class SweepSchedulerClientTellError(_message.Message):
    __slots__ = ("optimizer_run_id", "message")
    OPTIMIZER_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    optimizer_run_id: str
    message: str
    def __init__(self, optimizer_run_id: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class SweepSchedulerClientTaskError(_message.Message):
    __slots__ = ("message", "traceback")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TRACEBACK_FIELD_NUMBER: _ClassVar[int]
    message: str
    traceback: str
    def __init__(self, message: _Optional[str] = ..., traceback: _Optional[str] = ...) -> None: ...
