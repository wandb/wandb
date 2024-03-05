"""Terminal output functions for wini."""

from typing import Dict, List, Optional

import rich
from rich.padding import Padding
from rich.pretty import Pretty
from rich.text import Text


def info(msg: str) -> None:
    """Prints an informational message to tell the user what's happening."""
    text = Text(msg)
    text.stylize("bold white")
    rich.print(text)


def command(parts: List[str], env: Optional[Dict[str, str]] = None) -> None:
    """Prints out a terminal command."""
    rich.print(Padding(Pretty(parts), (0, 2)))
    if env:
        rich.print(Padding("with environment variables:", (0, 2)))
        rich.print(Padding(Pretty(env), (0, 2)))


def error(msg: str) -> None:
    """Prints an error message to tell the user something is wrong."""
    text = Text(msg)
    text.stylize("red")
    rich.print(text)
