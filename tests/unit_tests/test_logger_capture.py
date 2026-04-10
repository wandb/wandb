import logging
from unittest.mock import MagicMock

from wandb.sdk.lib.logger_capture import WandbLoggerHandler


class TestWandbLoggerHandler:
    """Tests for the WandbLoggerHandler class."""

    def _make_logger(self, name):
        """Create a uniquely-named logger for test isolation."""
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        return logger

    def test_handler_calls_callback_with_formatted_output(self):
        """The handler calls the callback with ('stdout', formatted_message)."""
        callback = MagicMock()
        handler = WandbLoggerHandler(callback=callback, level=logging.INFO)
        logger = self._make_logger("test_basic")
        logger.addHandler(handler)
        try:
            logger.info("hello world")
        finally:
            logger.removeHandler(handler)

        callback.assert_called_once()
        name, data = callback.call_args[0]
        assert name == "stdout"
        assert "hello world" in data

    def test_handler_output_ends_with_newline(self):
        """Formatted output ends with a newline to match print() behavior."""
        callback = MagicMock()
        handler = WandbLoggerHandler(callback=callback, level=logging.INFO)
        logger = self._make_logger("test_newline")
        logger.addHandler(handler)
        try:
            logger.info("test message")
        finally:
            logger.removeHandler(handler)

        _, data = callback.call_args[0]
        assert data.endswith("\n")

    def test_handler_format_includes_level_and_logger_name(self):
        """Formatted output contains the log level and logger name."""
        callback = MagicMock()
        handler = WandbLoggerHandler(callback=callback, level=logging.DEBUG)
        logger = self._make_logger("my_app.training")
        logger.addHandler(handler)
        try:
            logger.warning("something went wrong")
        finally:
            logger.removeHandler(handler)

        _, data = callback.call_args[0]
        assert "WARNING" in data
        assert "my_app.training" in data
        assert "something went wrong" in data

    def test_handler_respects_level(self):
        """A WARNING-level handler ignores INFO records."""
        callback = MagicMock()
        handler = WandbLoggerHandler(callback=callback, level=logging.WARNING)
        logger = self._make_logger("test_level")
        logger.addHandler(handler)
        try:
            logger.info("should be ignored")
            logger.warning("should be captured")
        finally:
            logger.removeHandler(handler)

        callback.assert_called_once()
        _, data = callback.call_args[0]
        assert "should be captured" in data

    def test_handler_captures_at_and_above_level(self):
        """An INFO-level handler captures INFO, WARNING, ERROR but not DEBUG."""
        callback = MagicMock()
        handler = WandbLoggerHandler(callback=callback, level=logging.INFO)
        logger = self._make_logger("test_multi_level")
        logger.addHandler(handler)
        try:
            logger.debug("debug msg")
            logger.info("info msg")
            logger.warning("warning msg")
            logger.error("error msg")
        finally:
            logger.removeHandler(handler)

        assert callback.call_count == 3
        calls = [call.args[1] for call in callback.call_args_list]
        assert "info msg" in calls[0]
        assert "warning msg" in calls[1]
        assert "error msg" in calls[2]

    def test_handler_does_not_propagate_callback_errors(self):
        """A broken callback must not crash the user's logger.error() call."""
        callback = MagicMock(side_effect=RuntimeError("callback broke"))
        handler = WandbLoggerHandler(callback=callback, level=logging.INFO)
        logger = self._make_logger("test_error_handling")
        logger.addHandler(handler)
        try:
            # This should NOT raise — the handler must swallow the error
            logger.error("this should not crash")
        finally:
            logger.removeHandler(handler)

        callback.assert_called_once()

    def test_default_settings_has_no_capture_loggers(self):
        """Settings() without console_capture_loggers leaves it as None."""
        from wandb import Settings

        settings = Settings()
        assert settings.console_capture_loggers is None
