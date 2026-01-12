from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass, fields
from typing import Any, Literal

Command = Literal["gke", "gce"]


@dataclass
class GKEConfig:
    cluster_name: str = "sdk-nightly"
    num_nodes: int = 1
    machine_type: str = "n1-standard-8"
    maintenance_policy: str = "TERMINATE"
    disk_size: str = "100GB"
    disk_type: str = "pd-ssd"
    accelerator_type: str = "nvidia-tesla-t4"
    accelerator_count: int = 1


@dataclass
class GCEConfig:
    instance_name: str = "sdk-compute"
    num_nodes: int = 1
    machine_type: str = "n1-highcpu-4"
    maintenance_policy: str = "TERMINATE"
    disk_size: str = "10GB"
    disk_type: str = "pd-ssd"
    # accelerator_type: str = "nvidia-tesla-t4"
    # accelerator_count: int = 1
    container_registry: str = "gcr.io"
    gcp_project_id: str = "wandb-client-cicd"
    project: str = "ubuntu-os-cloud"
    vm_image_name: str = "ubuntu-2004-focal-v20221018"
    python_version: str = "3.8"
    git_branch: str = "main"
    test_args: str = "--all"
    wandb_version: str = "0.13.6"


class Logger:
    def __init__(
        self,
        name: str,
        verbose: bool = False,
        log_level: int = logging.INFO,
    ) -> None:
        self.name = name
        self.verbose = verbose

        self.logger = logging.getLogger(name)
        handler = logging.FileHandler(f"{name}.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(log_level)

        # self.print("Initialized CLI")
        # self.print(self.config)

    def print(
        self,
        *args: Any,
        sep: str = " ",
        end: str = "\n",
        file=None,
    ) -> None:
        self.logger.info(sep.join(map(str, args)))
        if self.verbose:
            print(*args, sep=sep, end=end, file=file)


class GKE:
    """A simple CLI for managing GKE clusters.

    It is assumed that the user has installed the Google Cloud SDK with
    the required components (gke-gcloud-auth-plugin and kubectl) and has
    authenticated with the Google Cloud Platform.
    """

    def __init__(
        self,
        config: GKEConfig,
        verbose: bool = False,
        log_level: int = logging.INFO,
    ) -> None:
        self.config = config
        self.logger = Logger(__name__.lower(), verbose, log_level)

        self.logger.print(f"Initialized {__name__} CLI")
        self.logger.print(self.config)

        self.update_components()

    @staticmethod
    def update_components() -> None:
        subprocess.run(["gcloud", "--quiet", "components", "update"])

    @staticmethod
    def install_components() -> None:
        for component in ["gke-gcloud-auth-plugin", "kubectl"]:
            subprocess.run(["gcloud", "--quiet", "components", "install", component])

    def create_cluster(self) -> None:
        subprocess.run(
            [
                "gcloud",
                "container",
                "clusters",
                "create",
                self.config.cluster_name,
                "--num-nodes",
                str(self.config.num_nodes),
                "--machine-type",
                self.config.machine_type,
                "--disk-size",
                self.config.disk_size,
                "--disk-type",
                self.config.disk_type,
                "--accelerator",
                f"type={self.config.accelerator_type},count={self.config.accelerator_count}",
            ]
        )

    def get_cluster_credentials(self) -> None:
        subprocess.run(
            [
                "gcloud",
                "container",
                "clusters",
                "get-credentials",
                self.config.cluster_name,
            ]
        )

    def delete_cluster(self) -> None:
        subprocess.run(
            ["gcloud", "container", "clusters", "delete", self.config.cluster_name]
        )


class GCE:
    def __init__(
        self,
        config: GCEConfig,
        verbose: bool = False,
        log_level: int = logging.INFO,
    ) -> None:
        self.config = config
        self.logger = Logger(__name__.lower(), verbose, log_level)

        self.logger.print(f"Initialized {__name__} CLI")
        self.logger.print(self.config)

        self.update_components()

    @staticmethod
    def update_components() -> None:
        subprocess.run(["gcloud", "--quiet", "components", "update"])

    def create_vm(self) -> int:
        """Create the VM.

        - The first command creates a VM similar to the one
          the user can get from the GCP marketplace.
          - There is apparently no way to "interact" with the
            GCP marketplace directly.
        - The VMI explicitly asks to install GPU drivers on the first boot,
          so the second command does it.

        :return:
        """
        cmd = [
            "gcloud",
            "compute",
            "instances",
            "create",
            self.config.instance_name,
            "--machine-type",
            self.config.machine_type,
            "--maintenance-policy",
            self.config.maintenance_policy,
            "--image",
            f"projects/{self.config.project}/global/images/{self.config.vm_image_name}",
            "--boot-disk-size",
            self.config.disk_size,
            "--boot-disk-type",
            self.config.disk_type,
            # "--accelerator",
            # f"type={self.config.accelerator_type},"
            # f"count={self.config.accelerator_count}",
        ]
        self.logger.print(" ".join(cmd))
        p = subprocess.run(cmd)

        return p.returncode

        # # Agree to NVIDIA's prompt and install the GPU driver.
        # # This monster below is here bc the yes command
        # # and a gazillion alternatives do not work on circleci.
        # # reverse-engineered from /usr/bin/gcp-ngc-login.sh
        # cmd = [
        #     "gcloud",
        #     "compute",
        #     "ssh",
        #     self.config.instance_name,
        #     "--command",
        #     "source /etc/nvidia-vmi-version.txt; "
        #     'REGISTRY="nvcr.io"; NVIDIA_DIR="/var/tmp/nvidia"; '
        #     "sudo gsutil cp "
        #     "gs://nvidia-ngc-drivers-us-public/TESLA/shim/NVIDIA-Linux-x86_64-"
        #     "${NVIDIA_DRIVER_VERSION}-${NVIDIA_GCP_VERSION}-shim.run "
        #     "${NVIDIA_DIR}; "
        #     "sudo chmod u+x ${NVIDIA_DIR}/NVIDIA-Linux-x86_64-"
        #     "${NVIDIA_DRIVER_VERSION}-${NVIDIA_GCP_VERSION}-shim.run; "
        #     "sudo ${NVIDIA_DIR}/NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}-"
        #     "${NVIDIA_GCP_VERSION}-shim.run --no-cc-version-check "
        #     "--kernel-module-only --silent --dkms; "
        #     "sudo dkms add nvidia/${NVIDIA_DRIVER_VERSION} || true; "
        #     "cd /usr/share/doc/NVIDIA_GLX-1.0/samples/; "
        #     "sudo tar xvjf nvidia-persistenced-init.tar.bz2; "
        #     "sudo nvidia-persistenced-init/install.sh && "
        #     "sudo rm -rf nvidia-persistenced-init; ",
        # ]
        # self.logger.print(cmd)
        # for _ in range(6):
        #     p = subprocess.run(cmd)
        #     if p.returncode == 0:
        #         self.logger.print("GPU driver installed")
        #         break
        #     else:
        #         # allow some time for the VM to boot
        #         self.logger.print("Waiting for VM to boot...")
        #         time.sleep(10)
        #
        # return p.returncode

    def run(self) -> int:
        """Run the VM.

        :return:
        """
        cmd = [
            "gcloud",
            "compute",
            "ssh",
            self.config.instance_name,
            "--command",
            "sudo apt update; "
            "sudo apt install -y python3-pip; "
            "pip3 install --upgrade pip; "
            "pip3 install --upgrade wheel; "
            "pip3 install --upgrade wandb distributed; ",
            # "wandb login; ",
        ]
        self.logger.print(" ".join(cmd))
        p = subprocess.run(cmd)

        return p.returncode

    def delete_vm(self) -> int:
        """Delete the VM.

        :return:
        """
        p = subprocess.run(
            [
                "gcloud",
                "compute",
                "instances",
                "delete",
                self.config.instance_name,
                "--quiet",
            ]
        )
        return p.returncode


if __name__ == "__main__":
    commands: list[Command] = ["gke", "gce"]

    parser = argparse.ArgumentParser()

    # add verbose option
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="print verbose output",
    )

    subparsers = parser.add_subparsers(
        dest="target", title="target", description="target platform"
    )

    subparsers_store = {command: subparsers.add_parser(command) for command in commands}

    for command, subparser in subparsers_store.items():
        try:
            cli = getattr(sys.modules[__name__], command.upper())
        except AttributeError:
            continue

        actions = [
            func
            for func in dir(cli)
            if callable(getattr(cli, func)) and not func.startswith("__")
        ]

        subparser.add_argument("command", choices=actions, help="command to run")

        target_config = getattr(sys.modules[__name__], f"{command.upper()}Config")
        for field in fields(target_config):
            subparser.add_argument(
                f"--{field.name}",
                type=field.type,
                default=field.default,
                help=f"type: {field.type.__name__}; default: {field.default}",
            )

    parser_arguments = vars(parser.parse_args())
    print(parser_arguments)

    target = parser_arguments.pop("target")
    v = parser_arguments.pop("verbose")
    command = parser_arguments.pop("command")

    cli_class = getattr(sys.modules[__name__], target.upper())
    config_class = getattr(sys.modules[__name__], f"{target.upper()}Config")
    cli = cli_class(config=config_class(**parser_arguments), verbose=v)
    exit_code = getattr(cli, command)()
    sys.exit(exit_code)
