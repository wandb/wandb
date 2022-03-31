import os
import subprocess


def check_pip():
    try:
        import pip
    except ImportError:
        print("pip not installed")
        return False
    return True


def maybe_install_pip():
    if not check_pip():
        print("installing pip")

        subprocess.check_call(["sudo", "yum", "install", "python3-pip"])


def check_wandb():
    try:
        import wandb
    except ImportError:
        print("wandb not installed")
        return False
    return True


def check_curl():
    try:
        subprocess.check_call(["which", "curl"])
    except subprocess.CalledProcessError:
        print("curl not installed")
        return False


def maybe_install_curl():
    if not check_curl():
        print("installing curl")
        subprocess.check_call(["sudo", "yum", "install", "curl"])


def maybe_install_wandb():
    if not check_wandb():
        print("installing wandb")
        maybe_install_curl()
        maybe_install_pip()
        subprocess.check_call(["pip", "install", "wandb"])


if __name__ == "__main__":
    maybe_install_wandb()
    subprocess.call(["wandb", "login"])
