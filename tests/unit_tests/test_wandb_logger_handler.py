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

    def _make_mock_run(self):
        """Create a mock run with a write_logs method."""
        run = MagicMock()
        run.write_logs = MagicMock()
        return run

    def test_handler_calls_write_logs(self):
        """The handler calls run.write_logs with the formatted message."""
        run = self._make_mock_run()
        handler = WandbLoggerHandler(run, level=logging.INFO)
        logger = self._make_logger("test_basic")
        logger.addHandler(handler)
        try:
            logger.info("hello world")
        finally:
            logger.removeHandler(handler)

        run.write_logs.assert_called_once()
        text = run.write_logs.call_args[0][0]
        assert "hello world" in text

    def test_handler_respects_level(self):
        """A WARNING-level handler ignores INFO records."""
        run = self._make_mock_run()
        handler = WandbLoggerHandler(run, level=logging.WARNING)
        logger = self._make_logger("test_level")
        logger.addHandler(handler)
        try:
            logger.info("should be ignored")
            logger.warning("should be captured")
        finally:
            logger.removeHandler(handler)

        run.write_logs.assert_called_once()
        text = run.write_logs.call_args[0][0]
        assert "should be captured" in text

    def test_handler_captures_at_and_above_level(self):
        """An INFO-level handler captures INFO, WARNING, ERROR but not DEBUG."""
        run = self._make_mock_run()
        handler = WandbLoggerHandler(run, level=logging.INFO)
        logger = self._make_logger("test_multi_level")
        logger.addHandler(handler)
        try:
            logger.debug("debug msg")
            logger.info("info msg")
            logger.warning("warning msg")
            logger.error("error msg")
        finally:
            logger.removeHandler(handler)

        assert run.write_logs.call_count == 3
        calls = [call.args[0] for call in run.write_logs.call_args_list]
        assert "info msg" in calls[0]
        assert "warning msg" in calls[1]
        assert "error msg" in calls[2]

    def test_handler_does_not_propagate_errors(self):
        """A broken run.write_logs must not crash the user's logger call."""
        run = self._make_mock_run()
        run.write_logs.side_effect = RuntimeError("write_logs broke")
        handler = WandbLoggerHandler(run, level=logging.INFO)
        logger = self._make_logger("test_error_handling")
        logger.addHandler(handler)
        try:
            # This should NOT raise
            logger.error("this should not crash")
        finally:
            logger.removeHandler(handler)

        run.write_logs.assert_called_once()

    def test_handler_respects_custom_formatter(self):
        """Users can set their own formatter on the handler."""
        run = self._make_mock_run()
        handler = WandbLoggerHandler(run, level=logging.INFO)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger = self._make_logger("test_formatter")
        logger.addHandler(handler)
        try:
            logger.info("custom format")
        finally:
            logger.removeHandler(handler)

        text = run.write_logs.call_args[0][0]
        assert text == "[INFO] custom format"

    def test_handler_default_level_is_notset(self):
        """Default level is NOTSET, capturing everything."""
        run = self._make_mock_run()
        handler = WandbLoggerHandler(run)
        assert handler.level == logging.NOTSET
