import logging
import random
import string
import subprocess
from pathlib import Path


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


def generate_random_dict(num_fields: int, field_size: int) -> dict:
    """Generates a JSON-like dict with the specified number of fields and field sizes.

    Args:
        num_fields (int): The number of key-value pairs (fields) in the JSON.
        field_size (int): The size (in characters) of the field values.

    Returns:
        str: A JSON-like string with the specified structure.
    """

    def random_key():
        # Generate a random key with a length "field_size"  characters
        return "".join(
            random.choices(string.ascii_letters + string.digits + "_", k=field_size)
        )

    # Generate the specified number of fields
    return {random_key(): random.randint(1, 10**6) for _ in range(num_fields)}


def capture_sar_metrics(log_dir: str, iteration: int = 8):
    """Captures sar system metrics in the background and saves them to log files.

    This function starts the sar processes in the background in a fire-and-forget
    manner. This is because we want to support common scenarios where a load test
    may finish earlier than the metrics capturing sub-processes. A few things to
    note:

    1) No need to wait for the subprocesses to finish.
    Because these processes will exit on their own regardless of the parent
    process. There won't be any resource leaks. They are meant to be running in the
    background while the actual load testing runs on the main thread independently.

    2) Safe to have multiple runs
    Because they write metrics to a different log directory each time, there is no conflict
    even if multiples of these processes run in parallel.

    3) No need to manage them
    These sub processes are explicitly allowed to outlive the parent process. Therefore,
    there is no need to use a context manager to manage them.

    Args:
        log_dir (str): Directory where the log files will be saved.
        iteration (int): Number of seconds to capture metrics. Default is 8.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    commands = {
        "cpu.log": ["sar", "-u", "ALL", "1", str(iteration)],
        "mem.log": ["sar", "-r", "1", str(iteration)],
        "network.sock.log": ["sar", "-n", "SOCK", "1", str(iteration)],
        "network.dev.log": ["sar", "-n", "DEV", "1", str(iteration)],
        "paging.log": ["sar", "-B", "1", str(iteration)],
        "disk.log": ["sar", "-d", "-p", "1", str(iteration)],
    }

    for log_file, command in commands.items():
        log_file_path = log_path / log_file
        try:
            subprocess.Popen(
                command, stdout=open(log_file_path, "w"), stderr=subprocess.PIPE
            )
        except Exception as e:
            print(
                f"Error spawning subprocess {command} writing to {log_file_path}: {e}"
            )
