from __future__ import annotations

from cwsandbox import Session as CWSandboxSession

from ._sandbox import Sandbox


class Session(CWSandboxSession):
    """W&B-aware wrapper around `cwsandbox.Session`."""

    @classmethod
    def _sandbox_class(cls) -> type[Sandbox]:
        return Sandbox
