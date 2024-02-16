"""Functions for declaring and patching command-line arguments as part of a run template."""

import argparse
from typing import Any


class CliArg:
    """A class for declaring a single command-line argument as part of a run template."""

    def __init__(
        self,
        name: str,
        type: Any = str,
        help: str = "",
        default: Any = None,
        nargs: Any = None,
    ):
        """Initialize a CliArg object."""
        self.name = name
        self.type = type
        self.help = help
        self.default = default
        self.nargs = nargs


class CliParser:
    """A class for extracting run template parameters from a command line argument parser."""

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser

    def extract_schema(self) -> dict:
        """Extract the schema of the command line argument parser."""
        return extract_parser_schema(self.parser)


def add_action(action: argparse.Action, parent_structure: Any):
    """Recursively add subparser actions to the CLI structure."""
    if isinstance(action, argparse._SubParsersAction):
        # Handle subcommands
        for choice, subparser in action.choices.items():
            command_structure = {
                "name": choice,
                "description": subparser.description,
                "options": [],
                "arguments": [],
                "subcommands": [],  # This doesn't handle nested sub-subcommands
            }
            # Recursively add subparser actions
            for sub_action in subparser._actions:
                add_action(sub_action, command_structure)
            parent_structure["subcommands"].append(command_structure)
    elif isinstance(action, argparse._StoreTrueAction) or isinstance(
        action, argparse._StoreFalseAction
    ):
        parent_structure["options"].append(
            {
                "name": action.option_strings[0],
                "action": "store_true"
                if isinstance(action, argparse._StoreTrueAction)
                else "store_false",
                "help": action.help,
            }
        )
    elif isinstance(action, argparse._StoreAction):
        if action.option_strings:  # Option
            option = {
                "name": action.option_strings[0],
                "type": type(action.type).__name__ if action.type else "string",
                "help": action.help,
            }
            if action.default is not argparse.SUPPRESS and action.default is not None:
                option["default"] = action.default
            if action.nargs is not None:
                option["nargs"] = str(action.nargs)
            parent_structure["options"].append(option)
        else:  # Positional Argument
            argument = {
                "name": action.dest,
                "type": type(action.type).__name__ if action.type else "string",
                "help": action.help,
            }
            if action.nargs is not None:
                argument["nargs"] = str(action.nargs)
            parent_structure["arguments"].append(argument)


def extract_parser_schema(parser: argparse.ArgumentParser):
    """Converts an argparse.ArgumentParser instance to a YAML-compatible dict, including top-level options."""
    # Initialize the CLI structure
    cli_structure: Any = {
        "name": parser.prog,
        "description": parser.description,
        "options": [],
        "arguments": [],
        "subcommands": [],  # Subcommands
    }

    # Add top-level parser actions
    for action in parser._actions:
        add_action(action, cli_structure)

    return cli_structure
