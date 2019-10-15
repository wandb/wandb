"""
Windows-related compatibility helpers.
"""
import re

_find_unsafe = re.compile(r'[\s<>|&^]').search


def quote_arg(s):
    """Based on shlex.quote in the standard library."""
    if not s:
        return '""'
    if _find_unsafe(s) is None:
        return s
    if s.startswith('"') and s.endswith('"'):
        return s

    # If we found an unsafe character, escape with double quotes.
    return '"' + s + '"'
