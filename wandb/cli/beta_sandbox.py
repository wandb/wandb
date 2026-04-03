"""Implements `wandb beta sandbox` by delegating to the cwsandbox CLI."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from functools import lru_cache
from typing import Any

import click


@lru_cache(maxsize=1)
def _load_cwsandbox_cli() -> click.Group:
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
    return cli


def _entity_override_context(entity: str | None):
    if not entity:
        return nullcontext()

    auth_module = importlib.import_module("wandb.sandbox._auth")
    return auth_module._override_auth_context(entity=entity)


def _cwsandbox_error_type() -> type[BaseException]:
    exceptions_module = importlib.import_module("cwsandbox.exceptions")
    return exceptions_module.CWSandboxError


def _wrap_cwsandbox_command(base_command: click.Command) -> click.Command:
    @click.pass_context
    def callback(ctx: click.Context, entity: str | None, **kwargs: Any) -> Any:
        try:
            with _entity_override_context(entity):
                return ctx.invoke(base_command.callback, **kwargs)
        except _cwsandbox_error_type() as exc:
            raise click.ClickException(str(exc)) from None

    return click.Command(
        name=base_command.name,
        callback=callback,
        params=[
            click.Option(
                ["-e", "--entity"],
                default=None,
                help="Override the W&B entity used for sandbox auth.",
            ),
            *base_command.params,
        ],
        help=base_command.help,
        short_help=base_command.short_help,
        epilog=base_command.epilog,
        options_metavar=base_command.options_metavar,
        add_help_option=base_command.add_help_option,
        no_args_is_help=base_command.no_args_is_help,
        hidden=base_command.hidden,
        deprecated=base_command.deprecated,
        context_settings=base_command.context_settings,
    )


class SandboxGroup(click.Group):
    """A click Group that lazily proxies sandbox commands to cwsandbox."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._wrapped_commands: dict[str, click.Command] = {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        return _load_cwsandbox_cli().list_commands(ctx)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        wrapped_command = self._wrapped_commands.get(cmd_name)
        if wrapped_command is not None:
            return wrapped_command

        base_command = _load_cwsandbox_cli().get_command(ctx, cmd_name)
        if base_command is None:
            return None

        wrapped_command = _wrap_cwsandbox_command(base_command)
        self._wrapped_commands[cmd_name] = wrapped_command
        return wrapped_command
