# Taken from: https://github.com/alexsdutton/www-authenticate
import re
from collections import OrderedDict
from typing import Any, Optional

_tokens = (
    ("token", re.compile(r"""^([!#$%&'*+\-.^_`|~\w/]+(?:={1,2}$)?)""")),
    ("token", re.compile(r'''^"((?:[^"\\]|\\\\|\\")+)"''')),
    (None, re.compile(r"^\s+")),
    ("equals", re.compile(r"^(=)")),
    ("comma", re.compile(r"^(,)")),
)


def _casefold(value: str) -> str:
    try:
        return value.casefold()
    except AttributeError:
        return value.lower()


class CaseFoldedOrderedDict(OrderedDict):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(_casefold(key))

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(_casefold(key), value)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(_casefold(key))  # type: ignore

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        return super().get(_casefold(key), default)

    def pop(self, key: str, default: Optional[Any] = None) -> Any:
        return super().pop(_casefold(key), default)


def _group_pairs(tokens: list) -> None:
    i = 0
    while i < len(tokens) - 2:
        if (
            tokens[i][0] == "token"
            and tokens[i + 1][0] == "equals"
            and tokens[i + 2][0] == "token"
        ):
            tokens[i : i + 3] = [("pair", (tokens[i][1], tokens[i + 2][1]))]
        i += 1


def _group_challenges(tokens: list) -> list:
    challenges = []
    while tokens:
        j = 1
        if len(tokens) == 1:
            pass
        elif tokens[1][0] == "comma":
            pass
        elif tokens[1][0] == "token":
            j = 2
        else:
            while j < len(tokens) and tokens[j][0] == "pair":
                j += 2
            j -= 1
        challenges.append((tokens[0][1], tokens[1:j]))
        tokens[: j + 1] = []
    return challenges


def parse(value: str) -> CaseFoldedOrderedDict:
    tokens = []
    while value:
        for token_name, pattern in _tokens:
            match = pattern.match(value)
            if match:
                value = value[match.end() :]
                if token_name:
                    tokens.append((token_name, match.group(1)))
                break
        else:
            raise ValueError("Failed to parse value")
    _group_pairs(tokens)

    challenges = CaseFoldedOrderedDict()
    for name, tokens in _group_challenges(tokens):  # noqa: B020
        args, kwargs = [], {}
        for token_name, value in tokens:
            if token_name == "token":
                args.append(value)
            elif token_name == "pair":
                kwargs[value[0]] = value[1]
        challenges[name] = (args and args[0]) or kwargs or None

    return challenges
