"""Finds GQL introspection in git diff patch output.

Takes the output of `git show -p --unified=0` and looks for added lines
that include GQL introspection. Outputs GitHub workflow "::error" commands.
"""

# ruff: noqa T201 (allow print())

from __future__ import annotations

import re
from collections import deque

MESSAGE = "Potential GraphQL introspection here."

file_context: str = ""
context: deque[str] = deque(maxlen=3)  # up to 3 lines of context for errors
file: str | None = None
line: int | None = None

while True:
    try:
        text = input()
    except EOFError:
        break

    # Extract file names and line numbers from patch headers:
    if text.startswith("+++ b/"):
        file = text[6:]
        file_context = file
        context.clear()
        continue
    if match := re.match(r"^@@ \S+ \+(\d+)", text):
        line = int(match.group(1))
        continue

    # Accumulate context to display before errors.
    #
    # GitHub replaces ::error printouts with their message in the logs,
    # making the logs a series of
    #   Error: Potential GraphQL introspection here.
    #   Error: Potential GraphQL introspection here.
    #   Error: Potential GraphQL introspection here.
    #   Error: Potential GraphQL introspection here.
    # lines that aren't useful on their own.
    if len(text) > 0 and text[0] in "+- ":
        context.append(text)

    # Check for added lines containing GQL introspection.
    if text.startswith("+"):
        if file is None or line is None:
            raise AssertionError

        if re.search(r"\b(__type|__schema)\b", text):
            if file_context:
                print("\n" + "*" * 80)
                print(file_context)
                print("*" * 80)
                file_context = ""  # don't repeat filename unnecessarily
            print("\n".join(context))
            context.clear()

            print(f"::error file={file},line={line}::{MESSAGE}")

        line += 1
