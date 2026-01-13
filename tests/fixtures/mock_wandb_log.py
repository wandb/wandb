from __future__ import annotations

import textwrap
import unittest.mock
from typing import Iterable

import pytest


@pytest.fixture
def mock_wandb_log(monkeypatch: pytest.MonkeyPatch) -> MockWandbLog:
    """Mocks the wandb.term*() methods for a test.

    This patches the termlog() / termwarn() / termerror() methods and returns
    a `MockWandbTerm` object that can be used to assert on their usage.

    The logging functions mutate global state (for repeat=False), making
    them unsuitable for tests. Use this fixture to assert that a message
    was logged.
    """
    # Only calls like this are stubbed:
    #   import wandb; wandb.termlog()
    #   from wandb.errors import term; term.termlog()
    #
    # Calls like this are NOT stubbed:
    #   from wandb.errors.term import termlog; termlog()

    termlog = unittest.mock.MagicMock()
    termwarn = unittest.mock.MagicMock()
    termerror = unittest.mock.MagicMock()

    monkeypatch.setattr("wandb.termlog", termlog)
    monkeypatch.setattr("wandb.termwarn", termwarn)
    monkeypatch.setattr("wandb.termerror", termerror)
    monkeypatch.setattr("wandb.errors.term.termlog", termlog)
    monkeypatch.setattr("wandb.errors.term.termwarn", termwarn)
    monkeypatch.setattr("wandb.errors.term.termerror", termerror)

    return MockWandbLog(termlog, termwarn, termerror)


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

    def assert_logged(self, msg: str) -> None:
        """Raise if no message passed to termlog() contains msg_re."""
        self._assert_logged(self._termlog, msg)

    def assert_warned(self, msg: str) -> None:
        """Raise if no message passed to termwarn() contains msg_re."""
        self._assert_logged(self._termwarn, msg)

    def assert_errored(self, msg: str) -> None:
        """Raise if no message passed to termerror() contains msg_re."""
        self._assert_logged(self._termerror, msg)

    def _assert_logged(
        self,
        termfunc: unittest.mock.MagicMock,
        expected_msg: str,
    ) -> None:
        messages = list(self._logs(termfunc))

        for msg in messages:
            if expected_msg in msg:
                return
        else:
            messages_pretty = textwrap.indent("\n".join(messages), ">    ")
            raise AssertionError(f"{expected_msg!r} not in any of\n{messages_pretty}")

    def _logs(self, termfunc: unittest.mock.MagicMock) -> Iterable[str]:
        # All the term*() functions have a similar API: the message is the
        # first argument, which may also be passed as a keyword argument called
        # "string".
        for call in termfunc.call_args_list:
            if "string" in call.kwargs:
                yield call.kwargs["string"]
            else:
                yield call.args[0]
