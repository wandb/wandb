import logging


def get_logger(name: str, log_file: str = "perf.log") -> logging.Logger:
    """Creates and configures a logger that writes to both screen and log file.

    Args:
        name (str): The name of the logger.
        log_file (str): The file to log messages to. Default is 'perf.log'.

    Returns:
        logging.Logger: The configured logger instance.
    """
    # Create a custom logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Set the desired level of logging

    # Create handlers for screen (console) and file logging
    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_file)

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
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
