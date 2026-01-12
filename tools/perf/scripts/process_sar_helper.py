from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def pre_process_network_sar_log(log_dir: str) -> str:
    """This helper function pre-processes the network.dev.log.

    Parse out the metrics of the device we are interested in. i.e. eth0.

    Args:
        log_dir (str): The directory containing the log files.

    Returns:
        str: The name of the processed network log file, or an empty string if processing fails.
    """
    network_log = Path(log_dir) / "network.dev.log"

    if network_log.is_file():
        # get the network device name starting with an "e"
        grep_output = subprocess.run(
            "ls /sys/class/net/ | grep ^e | tail -n 1",
            shell=True,
            text=True,
            capture_output=True,
        )
        dev = grep_output.stdout.strip()
        network_dev_specific_log = Path(log_dir) / f"network.dev.{dev}.log"

        # add two blank lines at the top of the file to
        # match the format of other sar output log files
        for _ in range(2):
            result = subprocess.run(
                f"echo '' >> {network_dev_specific_log}", shell=True
            )

        # grep and save the header line
        result = subprocess.run(
            f"grep IFACE {network_log} | head -n 1 >> {network_dev_specific_log}",
            shell=True,
        )

        # then grep for the rest of data
        result = subprocess.run(
            f"grep {dev} {network_log} >> {network_dev_specific_log}", shell=True
        )

        if result.returncode == 0:
            return f"network.dev.{dev}.log"
        else:
            logger.warning(result)

    return ""


def pre_process_disk_sar_log(log_dir: str) -> str:
    """This function pre-processes the disk.log.

    Parse out the metrics of the device we are interested in. i.e. sda or vda.

    Args:
        log_dir (str): The directory containing the log files.

    Returns:
        str: The name of the processed disk log file, or an empty string if processing fails.
    """
    disk_log = Path(log_dir) / "disk.log"
    if not disk_log.is_file():
        logger.error(f"{disk_log} not found!")
        return ""

    # Run the lsblk command to get the name and type of devices
    lsblk_output = subprocess.check_output(
        ["lsblk", "-d", "-n", "-o", "NAME,TYPE"], text=True
    )

    # Filter for lines containing "disk" and extract the disk names
    disk_names = [
        line.split()[0] for line in lsblk_output.strip().split("\n") if "disk" in line
    ]
    logger.debug(f"Found disk devices: {disk_names}")

    if not disk_names or len(disk_names) == 0:
        logger.error("Disk device not found!")
        return ""

    dev = disk_names[0]
    disk_dev_specific_log = Path(log_dir) / f"disk.{dev}.log"

    # add two blank lines at the top of the file to
    # match the format of other sar output log files
    for _ in range(2):
        result = subprocess.run(f"echo '' >> {disk_dev_specific_log}", shell=True)

    # grep and save the header line
    result = subprocess.run(
        f"grep DEV {disk_log} | head -n 1 | sed 's/DEV//' >> {disk_dev_specific_log}",
        shell=True,
    )

    # then grep for the rest of the data
    result = subprocess.run(
        f"grep {dev} {disk_log} | sed 's/{dev}//' >> {disk_dev_specific_log}",
        shell=True,
    )

    if result.returncode == 0:
        return f"disk.{dev}.log"
    else:
        logger.error(result)

    return ""


def process_sar_files(log_dir: str) -> None:
    """This function process all the sar log files in a given directory.

    Compute avg and max values for each data field, and write them to <log>.json.

    Args:
        log_dir (str): The directory containing the log files.
    """
    # Explicitly stop any running sar processes first. Even if they are explicitly
    # killed, they will exit on their own when done.
    try:
        subprocess.run("killall sar", check=True, shell=True)
        logger.info("kill sar executed successfully.")
    except FileNotFoundError:
        logger.exception(
            "Command not found. Make sure 'killall' is installed and in your PATH."
        )
    except Exception:
        logger.exception("An unexpected error occurred.")

    log_files = ["cpu.log", "mem.log", "network.sock.log", "paging.log"]

    pre_processed_network_log = pre_process_network_sar_log(log_dir)
    if pre_processed_network_log != "":
        log_files.append(pre_processed_network_log)

    pre_processed_disk_log = pre_process_disk_sar_log(log_dir)
    if pre_processed_disk_log != "":
        log_files.append(pre_processed_disk_log)

    # process all the sar log files
    for log_file in log_files:
        log = Path(log_dir) / log_file
        if log.is_file():
            compute_avg_and_max(log, log.with_suffix(".json"))
        else:
            logger.warning(f"{log} not found.")


def compute_avg_and_max(input_file: Path, output_file: Path) -> None:
    """Compute average and max values from the input file and write to a JSON file.

    Args:
        input_file (Path): The path to the input sar log file.
        output_file (Path): The path to the output JSON file to save results.
    """
    with input_file.open() as file:
        lines = file.readlines()

    # Extract headers and data
    headers = lines[2].split()[2:]  # Skip first two columns
    data_lines = lines[3:]  # Skip the first three lines

    # Initialize dictionaries to store sums and max values
    field_sums = {header: 0.0 for header in headers}
    field_max = {header: 0.0 for header in headers}

    # Process each line of data
    line_count = 0
    for line in data_lines:
        fields = line.split()[2:]  # Skip first two columns
        for i, value in enumerate(fields):
            field_sums[headers[i]] += float(value)
            field_max[headers[i]] = max(field_max[headers[i]], float(value))
        line_count += 1

    # Compute averages
    field_avg = {
        f"avg_{header}": round(field_sums[header] / line_count, 2) for header in headers
    }
    field_max = {
        f"max_{header}": round(value, 2) for header, value in field_max.items()
    }

    # Combine results
    result = {**field_avg, **field_max}

    # Write to JSON file
    with output_file.open("w") as json_file:
        json.dump(result, json_file, indent=4)

    logger.debug(f"System metrics written to {output_file}")


def capture_sar_metrics(log_dir: str, iteration: int = 60):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--directory", type=str, required=True, help="Directory of SAR logs"
    )
    args = parser.parse_args()

    log_directory = Path(args.directory)
    if not log_directory.is_dir():
        logger.error(f"Directory {args.directory} does not exist.")
        exit(1)

    process_sar_files(args.directory)
