"""Implements `wandb beta sandbox` by delegating to the cwsandbox CLI."""

from __future__ import annotations

import copy
import importlib
import sys
from typing import Any

import click


class SandboxGroup(click.Group):
    """A click Group that lazily proxies sandbox commands to cwsandbox."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._base_cli: click.Group | None = None
        self._wrapped_commands: dict[str, click.Command] = {}

    def _load_cwsandbox_cli(self) -> click.Group:
        if self._base_cli is None:
            if sys.version_info < (3, 11):
                raise click.ClickException(
                    "Sandbox CLI support requires Python 3.11 or newer because cwsandbox does not support older Python versions."
                )
            try:
                importlib.import_module("wandb.sandbox")
                cli_module = importlib.import_module("cwsandbox.cli")
            except ImportError as exc:
                raise click.ClickException(
                    "Sandbox CLI support is not installed. Install it with: pip install wandb[sandbox]"
                ) from exc

            cli = getattr(cli_module, "cli", None)
            if not isinstance(cli, click.Group):
                raise click.ClickException("Failed to load the cwsandbox CLI.")

            self._base_cli = cli
        return self._base_cli

    def list_commands(self, ctx: click.Context) -> list[str]:
        return self._load_cwsandbox_cli().list_commands(ctx)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        wrapped_command = self._wrapped_commands.get(cmd_name)
        if wrapped_command is not None:
            return wrapped_command

        base_command = self._load_cwsandbox_cli().get_command(ctx, cmd_name)
        if base_command is None:
            return None

        @click.pass_context
        def callback(ctx: click.Context, entity: str | None, **kwargs: Any) -> Any:
            from wandb.sandbox import CWSandboxError
            from wandb.sandbox._auth import _override_sandbox_entity

            try:
                with _override_sandbox_entity(entity=entity):
                    return ctx.invoke(base_command.callback, **kwargs)
            except CWSandboxError as exc:
                raise click.ClickException(str(exc)) from None

        wrapped_command = copy.copy(base_command)
        wrapped_command.callback = callback
        wrapped_command.params = [
            click.Option(
                ["-e", "--entity"],
                default=None,
                help="Override the W&B entity used for sandbox auth.",
            ),
            *base_command.params,
        ]
        self._wrapped_commands[cmd_name] = wrapped_command
        return wrapped_command
