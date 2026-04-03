from __future__ import annotations

import importlib

try:
    importlib.import_module("cwsandbox")
except ImportError as exc:
    raise ImportError(
        "cwsandbox is not installed. Please install it with: pip install wandb[sandbox]"
    ) from exc

from cwsandbox import (
    NetworkOptions,
    OperationRef,
    Process,
    ProcessResult,
    RemoteFunction,
    Sandbox,
    SandboxDefaults,
    SandboxStatus,
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
    "NetworkOptions",
    "OperationRef",
    "Process",
    "ProcessResult",
    "RemoteFunction",
    "Sandbox",
    "SandboxDefaults",
    "SandboxStatus",
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
