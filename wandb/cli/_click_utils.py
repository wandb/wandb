"""Shared click.Group helpers for the wandb CLI."""

from __future__ import annotations

from typing import Any

import click


class DefaultCommandGroup(click.Group):
    """A group that passes non-command arguments to a default command."""

    def __init__(
        self,
        *args: Any,
        default_cmd: str,
        usage: str | None = None,
        show_default_options: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd
        self._usage = usage
        self._show_default_options = show_default_options

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] in ctx.help_option_names:
            return super().parse_args(ctx, args)
        if not args or args[0].startswith("-") or args[0] not in self.commands:
            args = [self.default_cmd, *args]
        return super().parse_args(ctx, args)

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if self._usage is None:
            super().format_usage(ctx, formatter)
        else:
            formatter.write_usage(ctx.command_path, self._usage)

    def format_options(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        if not self._show_default_options:
            super().format_options(ctx, formatter)
            return

        options: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add_records(
            command: click.Command,
            command_ctx: click.Context,
        ) -> None:
            for param in command.get_params(command_ctx):
                record = param.get_help_record(command_ctx)
                if record is not None and record[0] not in seen:
                    seen.add(record[0])
                    options.append(record)

        add_records(self, ctx)
        if command := self.get_command(ctx, self.default_cmd):
            add_records(command, click.Context(command, parent=ctx))

        if options:
            with formatter.section("Options"):
                formatter.write_dl(options)
        self.format_commands(ctx, formatter)
