from __future__ import annotations

import os
import platform
import sys
from typing import Literal, Sequence
from urllib.parse import unquote

from pydantic import AnyHttpUrl, BaseModel, computed_field, field_validator

from wandb import util

from .lib.ipython import _get_python_type


def _get_program_relpath(program: str, root: str | None = None) -> str | None:
    if not program:
        return None

    root = root or os.getcwd()
    if not root:
        return None

    full_path_to_program = os.path.join(
        root, os.path.relpath(os.getcwd(), root), program
    )
    if os.path.exists(full_path_to_program):
        relative_path = os.path.relpath(full_path_to_program, start=root)
        if "../" in relative_path:
            return None
        return relative_path

    return None


class Settings(BaseModel, validate_assignment=True):
    """Settings for W&B."""

    # ???
    _args: Sequence[str] | None = None
    # The base URL for the W&B API.
    base_url: AnyHttpUrl = "https://api.wandb.ai"
    console: Literal["auto", "off", "wrap", "redirect", "wrap_raw", "wrap_emu"] = "auto"

    # Field validators.
    @field_validator("base_url", mode="before")
    @classmethod
    def validate_base_url(cls, value):
        return value.strip().rstrip("/")

    @field_validator("console", mode="after")
    @classmethod
    def validate_console(cls, value, info):
        if value != "auto":
            return value
        if (
            info.data._jupyter
            or (info.data.start_method == "thread")
            or not info.data._disable_service
            or info.data._windows
        ):
            value = "wrap"
        else:
            value = "redirect"
        return value

    # Computed fields.
    @computed_field
    @property
    def _aws_lambda(self) -> bool:
        """Check if we are running in a lambda environment."""
        from sentry_sdk.integrations.aws_lambda import get_lambda_bootstrap

        lambda_bootstrap = get_lambda_bootstrap()
        if not lambda_bootstrap or not hasattr(
            lambda_bootstrap, "handle_event_request"
        ):
            return False
        return True

    @computed_field
    @property
    def _code_path_local(self) -> str:
        return _get_program_relpath(self.program)

    @computed_field
    @property
    def _colab(self) -> bool:
        return "google.colab" in sys.modules

    @computed_field
    @property
    def _ipython(self) -> bool:
        return _get_python_type() == "ipython"

    @computed_field
    @property
    def _jupyter(self) -> bool:
        return _get_python_type() == "jupyter"

    @computed_field
    @property
    def _kaggle(self) -> bool:
        return util._is_likely_kaggle()

    @computed_field
    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

    @computed_field
    @property
    def _notebook(self) -> bool:
        return self._ipython or self._jupyter or self._colab or self._kaggle

    @computed_field
    @property
    def _offline(self) -> bool:
        return self.disabled or self.mode in ("offline", "dryrun")

    @computed_field
    @property
    def _platform(self) -> str:
        return f"{platform.system()}-{platform.machine()}".lower()

    @computed_field
    @property
    def _shared(self) -> bool:
        return self.mode == "shared"

    @computed_field
    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @computed_field
    @property
    def colab_url(self) -> AnyHttpUrl | None:
        if not self._colab:
            return None
        if self._jupyter_path and self._jupyter_path.startswith("fileId="):
            unescaped = unquote(self._jupyter_path)
            return "https://colab.research.google.com/notebook#" + unescaped
        return None
