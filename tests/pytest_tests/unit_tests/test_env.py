from unittest import mock
from typing import Optional

import pytest

from wandb.env import get_async_upload_concurrency_limit


class TestGetAsyncUploadConcurrencyLimit:
    def test_parses_env_var(self):
        assert (
            get_async_upload_concurrency_limit(
                env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": "123"}
            )
            == 123
        )

    def test_returns_none_if_not_given(self):
        assert get_async_upload_concurrency_limit(env={}) is None
        assert (
            get_async_upload_concurrency_limit(
                env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": ""}
            )
            is None
        )

    @mock.patch("wandb.errors.term.termwarn")
    def test_no_warn_if_absent_or_sensible(self, termwarn: mock.Mock):
        get_async_upload_concurrency_limit(env={})
        get_async_upload_concurrency_limit(
            env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": ""}
        )
        get_async_upload_concurrency_limit(
            env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": "123"}
        )
        termwarn.assert_not_called()

    @mock.patch("wandb.errors.term.termwarn")
    def test_warns_and_returns_none_if_unparseable(self, termwarn: mock.Mock):
        assert (
            get_async_upload_concurrency_limit(
                env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": "not an int"}
            )
            is None
        )

        termwarn.assert_called_once_with(mock.ANY, repeat=False)
        assert "Ignoring non-integer value" in termwarn.call_args[0][0]

    @pytest.mark.parametrize("env_var", ["-1", "0"])
    @mock.patch("wandb.errors.term.termwarn")
    def test_warns_and_returns_none_if_nonpositive(
        self, termwarn: mock.Mock, env_var: str
    ):
        assert (
            get_async_upload_concurrency_limit(
                env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": env_var}
            )
            is None
        )

        termwarn.assert_called_once_with(mock.ANY, repeat=False)
        assert "must be positive" in termwarn.call_args[0][0]

    @mock.patch("wandb.errors.term.termwarn")
    def test_warns_and_caps_if_exceeds_filelimit(self, termwarn: mock.Mock):
        assert (
            get_async_upload_concurrency_limit(
                env={"WANDB_ASYNC_UPLOAD_CONCURRENCY_LIMIT": "9999"},
                file_limit=234,
            )
            == 234 // 2
        )

        termwarn.assert_called_once_with(mock.ANY, repeat=False)
        assert "limit on open files" in termwarn.call_args[0][0]
