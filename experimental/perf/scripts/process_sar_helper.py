import argparse
import json
import os
import subprocess


def pre_process_network_sar_log(log_dir: str) -> str:
    """This helper function pre-processes the network.dev.log.

    Parse out the metrics of the device we are interested in. i.e. eth0.
    """
    network_log = os.path.join(log_dir, "network.dev.log")

    if os.path.isfile(network_log):
        dev = "eth0"
        network_dev_specific_log = os.path.join(log_dir, f"network.dev.{dev}.log")

        # add two blank lines at the top of the file to
        # match the format of other sar output log files
        for _ in range(2):
            command = f"echo '' >> {network_dev_specific_log}"
            result = subprocess.run(command, shell=True)

        # grep and save the header line
        command = f"grep IFACE {network_log} | head -n 1 >> {network_dev_specific_log}"
        result = subprocess.run(command, shell=True)

        # then grep for the rest of data
        command = f"grep {dev} {network_log} >> {network_dev_specific_log}"
        result = subprocess.run(command, shell=True)

        if result.returncode == 0:
            return f"network.dev.{dev}.log"
        else:
            print(f"WARNING: {result}")

    return ""


def pre_process_disk_sar_log(log_dir: str) -> str:
    """This function pre-processes the disk.log.

    Parse out the metrics of the device we are interested in. i.e. sda or vda.
    """
    disk_log = os.path.join(log_dir, "disk.log")
    dev = None

    if os.path.isfile(disk_log):
        # check to see if the disk device is named sda or vda
        disk_devices = ["sda", "vda"]
        for device in disk_devices:
            result = subprocess.run(f"grep {device} {disk_log} > /dev/null", shell=True)
            if result.returncode == 0:
                dev = device
                break
    else:
        return ""

    if dev is not None:
        disk_dev_specific_log = os.path.join(log_dir, f"disk.{dev}.log")

        # add two blank lines at the top of the file to
        # match the format of other sar output log files
        for _ in range(2):
            command = f"echo '' >> {disk_dev_specific_log}"
            result = subprocess.run(command, shell=True)

        # grep and save the header line
        command = f"grep DEV {disk_log} | head -n 1 | sed 's/DEV//' >> {disk_dev_specific_log}"
        result = subprocess.run(command, shell=True)

        # then grep for the rest of the data
        command = f"grep {dev} {disk_log} | sed 's/{dev}//' >> {disk_dev_specific_log}"
        result = subprocess.run(command, shell=True)

        if result.returncode == 0:
            return f"disk.{dev}.log"
        else:
            print(f"WARNING: {result}")

    else:
        print(f"WARNING: Neither sda nor vda was found in {disk_log}")

    return ""


def process_sar_files(log_dir: str):
    """This function process all the sar log files in a given directory.

    Compute avg and max values for each data field, and write them to <log>.json.
    """
    log_files = ["cpu.log", "mem.log", "network.sock.log", "paging.log"]

    pre_processed_network_log = pre_process_network_sar_log(log_dir)
    if pre_processed_network_log != "":
        log_files.append(pre_processed_network_log)

    pre_processed_disk_log = pre_process_disk_sar_log(log_dir)
    if pre_processed_disk_log != "":
        log_files.append(pre_processed_disk_log)

    # process all the sar log files
    for log_file in log_files:
        log = os.path.join(log_dir, log_file)
        if os.path.isfile(log):
            compute_avg_and_max(log, os.path.join(log_dir, log_file + ".json"))
        else:
            print(f"WARNING! {log} not found.")


def compute_avg_and_max(input_file, output_file):
    with open(input_file) as file:
        lines = file.readlines()

    # Extract headers and data
    headers = lines[2].split()[2:]  # Skip first two columns
    data_lines = lines[3:]  # Skip the first three lines

    # Initialize dictionaries to store sums and max values
    field_sums = {header: 0 for header in headers}
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
    with open(output_file, "w") as json_file:
        json.dump(result, json_file, indent=4)

    print(f"System metrics written to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--directory", type=str, required=True, help="Directory of SAR logs"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"ERROR! Directory {args.directory} does not exist.")
        exit(1)

    # stop any running sar processes
    subprocess.run("killall sar", shell=True)

    process_sar_files(args.directory)
