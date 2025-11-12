from __future__ import annotations

import unittest.mock
from typing import Iterable, Iterator

import pytest


@pytest.fixture
def mock_wandb_log() -> Iterator[MockWandbLog]:
    """Mocks the wandb.term*() methods for a test.

    This patches the termlog() / termwarn() / termerror() methods and returns
    a `MockWandbTerm` object that can be used to assert on their usage.

    The logging functions mutate global state (for repeat=False), making
    them unsuitable for tests. Use this fixture to assert that a message
    was logged.
    """
    # NOTE: This only stubs out calls like "wandb.termlog()", NOT
    # "from wandb.errors.term import termlog; termlog()".
    with unittest.mock.patch.multiple(
        "wandb",
        termlog=unittest.mock.DEFAULT,
        termwarn=unittest.mock.DEFAULT,
        termerror=unittest.mock.DEFAULT,
    ) as patched:
        yield MockWandbLog(
            patched["termlog"],
            patched["termwarn"],
            patched["termerror"],
        )


class MockWandbLog:
    """Helper to test wandb.term*() calls.

    See the `mock_wandb_log` fixture.
    """

    def __init__(
        self,
        termlog: unittest.mock.MagicMock,
        termwarn: unittest.mock.MagicMock,
        termerror: unittest.mock.MagicMock,
    ):
        self._termlog = termlog
        self._termwarn = termwarn
        self._termerror = termerror

    def logged(self, msg: str) -> bool:
        """Returns whether the message was included in a termlog()."""
        return self._logged(self._termlog, msg)

    def warned(self, msg: str) -> bool:
        """Returns whether the message was included in a termwarn()."""
        return self._logged(self._termwarn, msg)

    def errored(self, msg: str) -> bool:
        """Returns whether the message was included in a termerror()."""
        return self._logged(self._termerror, msg)

    def _logged(self, termfunc: unittest.mock.MagicMock, msg: str) -> bool:
        return any(msg in logged for logged in self._logs(termfunc))

    def _logs(self, termfunc: unittest.mock.MagicMock) -> Iterable[str]:
        # All the term*() functions have a similar API: the message is the
        # first argument, which may also be passed as a keyword argument called
        # "string".
        for call in termfunc.call_args_list:
            if "string" in call.kwargs:
                yield call.kwargs["string"]
            else:
                yield call.args[0]
