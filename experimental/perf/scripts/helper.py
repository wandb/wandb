import random
import string
import subprocess


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

    Args:
        log_dir (str): Directory where the log files will be saved.
        iteration (int): Number of seconds to capture metrics. Default is 8.
    """
    commands = {
        "cpu.log": ["sar", "-u", "ALL", "1", str(iteration)],
        "mem.log": ["sar", "-r", "1", str(iteration)],
        "network.sock.log": ["sar", "-n", "SOCK", "1", str(iteration)],
        "network.dev.log": ["sar", "-n", "DEV", "1", str(iteration)],
        "paging.log": ["sar", "-B", "1", str(iteration)],
        "disk.log": ["sar", "-d", "-p", "1", str(iteration)],
    }

    processes = []
    for log_file, command in commands.items():
        log_path = f"{log_dir}/{log_file}"
        process = subprocess.Popen(
            command, stdout=open(log_path, "w"), stderr=subprocess.PIPE
        )
        processes.append(process)

    # Wait for all subprocesses to complete
    # for process in processes:
    #    process.wait()
