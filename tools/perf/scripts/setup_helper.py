from __future__ import annotations

import logging

from . import _PACKAGE_LOGGER


def setup_package_logger() -> None:
    """Configure the package logger to write to a file and to the screen."""
    _PACKAGE_LOGGER.setLevel(logging.DEBUG)

    # Create handlers for screen (console) and file logging
    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler("perf.log")

    # Set the logging level for each handler
    console_handler.setLevel(logging.INFO)  # Info level for console
    file_handler.setLevel(logging.DEBUG)  # Debug level for file

    # Create a formatter and set it for both handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Add the handlers to the logger
    _PACKAGE_LOGGER.addHandler(console_handler)
    _PACKAGE_LOGGER.addHandler(file_handler)
