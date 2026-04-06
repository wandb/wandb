from __future__ import annotations

import importlib
import sys

if sys.version_info < (3, 11):
    raise ImportError(
        "wandb.sandbox requires Python 3.11 or newer because cwsandbox does not support older Python versions."
    )

try:
    importlib.import_module("cwsandbox")
except ImportError as exc:
    raise ImportError(
        "cwsandbox is not installed. Please install it with: pip install wandb[sandbox]"
    ) from exc

from cwsandbox import (
    AsyncFunctionError,
    CWSandboxAuthenticationError,
    CWSandboxError,
    FunctionError,
    FunctionSerializationError,
    NetworkOptions,
    OperationRef,
    Process,
    ProcessResult,
    RemoteFunction,
    Sandbox,
    SandboxDefaults,
    SandboxError,
    SandboxExecutionError,
    SandboxFailedError,
    SandboxFileError,
    SandboxNotFoundError,
    SandboxNotRunningError,
    SandboxStatus,
    SandboxTerminatedError,
    SandboxTimeoutError,
    Serialization,
    Session,
    StreamReader,
    StreamWriter,
    TerminalResult,
    TerminalSession,
    Waitable,
    results,
    wait,
)

from ._auth import _set_wandb_auth_mode
from ._secret import Secret

_set_wandb_auth_mode()

__all__ = (
    "AsyncFunctionError",
    "CWSandboxAuthenticationError",
    "CWSandboxError",
    "FunctionError",
    "FunctionSerializationError",
    "NetworkOptions",
    "OperationRef",
    "Process",
    "ProcessResult",
    "RemoteFunction",
    "Sandbox",
    "SandboxDefaults",
    "SandboxError",
    "SandboxExecutionError",
    "SandboxFailedError",
    "SandboxFileError",
    "SandboxNotFoundError",
    "SandboxNotRunningError",
    "SandboxStatus",
    "SandboxTerminatedError",
    "SandboxTimeoutError",
    "Secret",
    "Serialization",
    "Session",
    "StreamReader",
    "StreamWriter",
    "TerminalResult",
    "TerminalSession",
    "Waitable",
    "results",
    "wait",
)
