"""Compatibility rewrites for generated GraphQL documents."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import NamedTuple


class _Token(NamedTuple):
    value: str
    start: int
    end: int


def _graphql_tokens(query: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(query):
        char = query[i]
        if char.isspace():
            i += 1
        elif char == "#":
            newline = query.find("\n", i)
            i = len(query) if newline == -1 else newline
        elif char == '"':
            if query.startswith('"""', i):
                end = query.find('"""', i + 3)
                i = len(query) if end == -1 else end + 3
            else:
                i += 1
                while i < len(query):
                    if query[i] == "\\":
                        i += 2
                    elif query[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
        elif query.startswith("...", i):
            tokens.append(_Token("...", i, i + 3))
            i += 3
        elif char.isalpha() or char == "_":
            start = i
            i += 1
            while i < len(query) and (query[i].isalnum() or query[i] == "_"):
                i += 1
            tokens.append(_Token(query[start:i], start, i))
        elif char in "$(){}[]:!,=@":
            tokens.append(_Token(char, i, i + 1))
            i += 1
        else:
            i += 1
    return tokens


def _matching_token(tokens: list[_Token], start_idx: int) -> int | None:
    pairs = {"(": ")", "{": "}", "[": "]"}
    close = pairs.get(tokens[start_idx].value)
    if close is None:
        return None

    depth = 0
    for idx in range(start_idx, len(tokens)):
        value = tokens[idx].value
        if value == tokens[start_idx].value:
            depth += 1
        elif value == close:
            depth -= 1
            if depth == 0:
                return idx
    return None


def _line_range(query: str, start: int, end: int) -> tuple[int, int]:
    line_start = query.rfind("\n", 0, start) + 1
    line_end = query.find("\n", end)
    if line_end == -1:
        line_end = len(query)
        remove_end = line_end
    else:
        remove_end = line_end + 1

    if not query[line_start:start].strip() and not query[end:line_end].strip():
        return line_start, remove_end
    return start, end


def _apply_ranges(query: str, ranges: Iterable[tuple[int, int]]) -> str:
    for start, end in sorted(ranges, reverse=True):
        query = query[:start] + query[end:]
    return query


def _cleanup_graphql(query: str) -> str:
    query = re.sub(r",\s*\)", ")", query)
    query = re.sub(r"\(\s*,", "(", query)
    query = re.sub(r"\n{3,}", "\n\n", query)
    return query


def _omit_graphql_variable(query: str, variable: str) -> str:
    name = re.escape(variable)
    var_def_pattern = re.compile(
        rf"(?P<lead>,\s*)?\${name}\s*:\s*(?:\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*!?)(?:\s*=\s*[^,)]+)?(?P<trail>\s*,)?"
    )

    def replace_var_def(match: re.Match[str]) -> str:
        if match.group("lead") and match.group("trail"):
            return match.group("lead")
        return ""

    query = var_def_pattern.sub(replace_var_def, query)
    query = re.sub(
        rf"(?m)^[^\S\n]*[A-Za-z_][A-Za-z0-9_]*\s*:\s*\${name}\b[^\n,)]*,?\n?",
        "",
        query,
    )
    query = re.sub(
        rf"(?P<lead>,\s*)?[A-Za-z_][A-Za-z0-9_]*\s*:\s*\${name}\b(?P<trail>\s*,)?",
        lambda m: m.group("lead") if m.group("lead") and m.group("trail") else "",
        query,
    )
    return _cleanup_graphql(query)


def _fragment_definitions(query: str) -> dict[str, tuple[int, int, int, int]]:
    tokens = _graphql_tokens(query)
    fragments: dict[str, tuple[int, int, int, int]] = {}
    for idx, token in enumerate(tokens):
        if token.value != "fragment" or idx + 1 >= len(tokens):
            continue
        name = tokens[idx + 1].value
        brace_idx = next(
            (j for j in range(idx + 2, len(tokens)) if tokens[j].value == "{"),
            None,
        )
        if brace_idx is None:
            continue
        end_idx = _matching_token(tokens, brace_idx)
        if end_idx is None:
            continue
        start, end = _line_range(query, token.start, tokens[end_idx].end)
        fragments[name] = (start, end, tokens[brace_idx].start, tokens[end_idx].end)
    return fragments


def _omit_graphql_fragment(query: str, fragment: str) -> str:
    tokens = _graphql_tokens(query)
    ranges: list[tuple[int, int]] = []
    for idx, token in enumerate(tokens):
        if (
            token.value == "..."
            and idx + 1 < len(tokens)
            and tokens[idx + 1].value == fragment
        ):
            ranges.append(_line_range(query, token.start, tokens[idx + 1].end))

    if definition := _fragment_definitions(query).get(fragment):
        ranges.append((definition[0], definition[1]))

    return _cleanup_graphql(_apply_ranges(query, ranges))


def _field_range(query: str, tokens: list[_Token], idx: int) -> tuple[int, int] | None:
    if idx > 0 and tokens[idx - 1].value in {"fragment", "on", "$", "..."}:
        return None
    if idx + 1 < len(tokens) and tokens[idx + 1].value == ":":
        return None

    start_idx = idx
    if idx >= 2 and tokens[idx - 1].value == ":":
        start_idx = idx - 2

    end_idx = idx
    cursor = idx + 1
    while cursor < len(tokens):
        value = tokens[cursor].value
        if value in {"(", "{"}:
            match_idx = _matching_token(tokens, cursor)
            if match_idx is None:
                return None
            end_idx = match_idx
            cursor = match_idx + 1
        elif value == "@":
            cursor += 1
        elif value in {"}", ")"}:
            break
        elif value == ",":
            end_idx = cursor
            break
        else:
            end_idx = cursor
            cursor += 1
            if cursor < len(tokens) and tokens[cursor].value not in {"(", "{", "@"}:
                break

    return _line_range(query, tokens[start_idx].start, tokens[end_idx].end)


def _omit_graphql_field(query: str, field: str) -> str:
    tokens = _graphql_tokens(query)
    ranges: list[tuple[int, int]] = []
    for idx, token in enumerate(tokens):
        if token.value != field:
            continue
        if remove_range := _field_range(query, tokens, idx):
            ranges.append(remove_range)
    return _cleanup_graphql(_apply_ranges(query, ranges))


def _rename_graphql_field(query: str, old: str, new: str) -> str:
    tokens = _graphql_tokens(query)
    ranges: list[tuple[int, int, str]] = []
    for idx, token in enumerate(tokens):
        if token.value != old:
            continue
        if idx > 0 and tokens[idx - 1].value in {"fragment", "on", "$", "..."}:
            continue
        if idx + 1 < len(tokens) and tokens[idx + 1].value == ":":
            continue
        ranges.append((token.start, token.end, new))

    for start, end, replacement in sorted(ranges, reverse=True):
        query = query[:start] + replacement + query[end:]
    return query


def _remove_empty_selection_fields(query: str) -> str:
    while True:
        tokens = _graphql_tokens(query)
        ranges: list[tuple[int, int]] = []
        for idx, token in enumerate(tokens):
            if token.value != "{":
                continue
            end_idx = _matching_token(tokens, idx)
            if end_idx is None or query[token.end : tokens[end_idx].start].strip():
                continue
            if idx == 0 or tokens[idx - 1].value in {"query", "mutation", "fragment"}:
                continue
            if remove_range := _field_range(query, tokens, idx - 1):
                ranges.append(remove_range)
        if not ranges:
            return query
        query = _cleanup_graphql(_apply_ranges(query, ranges))


def _fragment_spreads(query: str) -> set[str]:
    tokens = _graphql_tokens(query)
    return {
        tokens[idx + 1].value
        for idx, token in enumerate(tokens[:-1])
        if token.value == "..."
    }


def _remove_orphan_fragments(query: str) -> str:
    fragments = _fragment_definitions(query)
    if not fragments:
        return query

    operation_text = query
    for start, end, _, _ in sorted(fragments.values(), reverse=True):
        operation_text = operation_text[:start] + operation_text[end:]

    used = _fragment_spreads(operation_text)
    queue = list(used)
    while queue:
        fragment = queue.pop()
        if fragment not in fragments:
            continue
        _, _, body_start, body_end = fragments[fragment]
        for nested in _fragment_spreads(query[body_start:body_end]):
            if nested not in used:
                used.add(nested)
                queue.append(nested)

    ranges = [
        (start, end)
        for name, (start, end, _, _) in fragments.items()
        if name not in used
    ]
    return _cleanup_graphql(_apply_ranges(query, ranges))


def gql_compat(
    request_string: str,
    omit_variables: Iterable[str] | None = None,
    omit_fragments: Iterable[str] | None = None,
    omit_fields: Iterable[str] | None = None,
    rename_fields: Mapping[str, str] | None = None,
) -> str:
    """Rewrite a generated GraphQL document for older server versions."""
    query = request_string
    if not (omit_variables or omit_fragments or omit_fields or rename_fields):
        return query

    for old, new in (rename_fields or {}).items():
        query = _rename_graphql_field(query, old, new)
    for variable in omit_variables or ():
        query = _omit_graphql_variable(query, variable)
    for fragment in omit_fragments or ():
        query = _omit_graphql_fragment(query, fragment)
    for field in omit_fields or ():
        query = _omit_graphql_field(query, field)
    query = _remove_empty_selection_fields(query)
    return _remove_orphan_fragments(query)
