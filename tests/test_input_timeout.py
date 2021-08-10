from wandb.sdk.lib.stdin_timeout import stdin_timeout
from wandb.errors import InputTimeoutError
import io
import pytest


@pytest.fixture
def input_timeout(monkeypatch):
    monkeypatch.setattr('sys.stdin', io.StringIO('1'))
    choice = stdin_timeout("", None, "")
    assert choice == '1'

