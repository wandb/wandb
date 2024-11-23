import argparse
import json
import os
import subprocess


def find_max(file_path: str, field: int) -> float:
    """Finds the maximum value in the N-th field of a log file.

    Args:
        file_path (str): Path to the log file.
        field (int): Column number to analyze (0-based indexing).

    Returns:
        float: The maximum value in the specified column.
    """
    max_value = 0.0

    with open(file_path) as file:
        for line in file:
            # Skip header lines
            if (
                line.strip() == ""
                or line.startswith("Linux")
                or line.startswith("Average:")
            ):
                continue

            # Split the line into columns
            parts = line.split()
            try:
                value = float(parts[field])
                max_value = max(max_value, value)
            except (ValueError, IndexError):
                continue

    return max_value


def process_sar_files(log_dir: str, json_output_file: str):
    """Process the sar files and write the summary to a json file.

    Args:
        log_dir (str): Path to the folder of sar log files.
        json_output_file (str): name of json output file.
    """
    json_data = {}

    # Process CPU logs
    cpu_log = os.path.join(log_dir, "cpu.log")
    if os.path.isfile(cpu_log):
        with open(cpu_log) as f:
            lines = f.readlines()
            if len(lines) > 2:
                cpu_values = lines[-1].split()
                json_data["avg_cpu_usr"] = float(cpu_values[2])
                json_data["avg_cpu_sys"] = float(cpu_values[4])
                json_data["avg_cpu_iowait"] = float(cpu_values[5])

                json_data["max_cpu_usr"] = find_max(cpu_log, 2)
                json_data["max_cpu_sys"] = find_max(cpu_log, 4)
                json_data["max_cpu_iowait"] = find_max(cpu_log, 5)
    else:
        print(f"WARNING! {cpu_log} not found.")

    # Process memory logs
    mem_log = os.path.join(log_dir, "mem.log")
    if os.path.isfile(mem_log):
        with open(mem_log) as f:
            lines = f.readlines()
            if len(lines) > 2:
                mem_values = lines[-1].split()
                json_data["avg_memused"] = float(mem_values[4])
                json_data["avg_memcommit"] = float(mem_values[8])

                json_data["max_memused"] = find_max(mem_log, 4)
                json_data["max_memcommit"] = find_max(mem_log, 8)
    else:
        print(f"WARNING! {mem_log} not found.")

    # Process network socket logs
    sock_log = os.path.join(log_dir, "network.sock.log")
    if os.path.isfile(sock_log):
        with open(sock_log) as f:
            lines = f.readlines()
            if len(lines) > 2:
                socket_values = lines[-1].split()
                json_data["avg_network_totsck"] = float(socket_values[1])
                json_data["avg_network_tcp_tw"] = float(socket_values[6])

                json_data["max_network_totsck"] = find_max(sock_log, 1)
                json_data["max_network_tcp_tw"] = find_max(sock_log, 6)
    else:
        print(f"WARNING! {sock_log} not found.")

    # Process network device logs (e.g., eth0)
    network_log = os.path.join(log_dir, "network.dev.log")
    if os.path.isfile(network_log):
        dev = "eth0"
        network_dev_specific_log = os.path.join(log_dir, f"network.dev.{dev}.log")
        command = f"grep {dev} {network_log} > {network_dev_specific_log}"
        result = subprocess.run(command, shell=True)

        if result.returncode == 0:
            with open(network_dev_specific_log) as f:
                lines = f.readlines()
                if len(lines) > 2:
                    last_line = lines[-1].split()
                    json_data[f"avg_{dev}_rxkBps"] = float(last_line[4])
                    json_data[f"avg_{dev}_txkBps"] = float(last_line[5])
                    json_data[f"avg_{dev}_ifutil"] = float(last_line[9])

                    json_data[f"max_{dev}_rxkBps"] = find_max(
                        network_dev_specific_log, 4
                    )
                    json_data[f"max_{dev}_txkBps"] = find_max(
                        network_dev_specific_log, 5
                    )
                    json_data[f"max_{dev}_ifutil"] = find_max(
                        network_dev_specific_log, 9
                    )
        else:
            print(f"WARNING: {result}")
    else:
        print(f"WARNING! {network_log} not found.")

    # Process disk logs
    disk_log = os.path.join(log_dir, "disk.log")
    if os.path.isfile(disk_log):
        dev = "da"
        disk_dev_specific_log = os.path.join(log_dir, f"disk.{dev}.log")
        disk_cmd = f"grep -E 'sda|vda' {disk_log} > {disk_dev_specific_log}"
        result = subprocess.run(disk_cmd, shell=True)

        if result.returncode == 0:
            with open(disk_dev_specific_log) as f:
                lines = f.readlines()
                if len(lines) > 2:
                    last_line = lines[-1].split()
                    json_data[f"avg_disk_{dev}_tps"] = float(last_line[1])
                    json_data[f"avg_disk_{dev}_rkBp"] = float(last_line[2])
                    json_data[f"avg_disk_{dev}_wkBps"] = float(last_line[3])
                    json_data[f"avg_disk_{dev}_aqu_sz"] = float(last_line[6])
                    json_data[f"avg_disk_{dev}_await"] = float(last_line[7])
                    json_data[f"avg_disk_{dev}_util"] = float(last_line[8])

                    json_data[f"max_disk_{dev}_tps"] = find_max(
                        disk_dev_specific_log, 1
                    )
                    json_data[f"max_disk_{dev}_rkBp"] = find_max(
                        disk_dev_specific_log, 2
                    )
                    json_data[f"max_disk_{dev}_wkBps"] = find_max(
                        disk_dev_specific_log, 3
                    )
                    json_data[f"max_disk_{dev}_aqu_sz"] = find_max(
                        disk_dev_specific_log, 6
                    )
                    json_data[f"max_disk_{dev}_await"] = find_max(
                        disk_dev_specific_log, 7
                    )
                    json_data[f"max_disk_{dev}_util"] = find_max(
                        disk_dev_specific_log, 8
                    )
        else:
            print(f"WARNING: {result}")
    else:
        print(f"WARNING! {disk_log} not found.")

    # Write JSON to file
    output_path = os.path.join(log_dir, json_output_file)
    with open(output_path, "w") as outfile:
        json.dump(json_data, outfile, indent=4)
    print(f"JSON metrics saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--directory", type=str, required=True, help="Directory of SAR logs"
    )
    parser.add_argument(
        "-o", "--output", type=str, required=True, help="Output JSON file"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"ERROR! Directory {args.directory} does not exist.")
        exit(1)

    process_sar_files(args.directory, args.output)
