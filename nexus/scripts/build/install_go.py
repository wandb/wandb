import os
import platform
import subprocess

VERSION = "1.21.1"


def go_get_go():
    system = platform.system().lower()
    machine = platform.machine().lower().replace("x86_64", "amd64")
    extension = "tar.gz" if system != "windows" else "msi"
    out_path = "/usr/local" if system == "linux" else "/tmp/go"

    file_name = f"go{VERSION}.{system}-{machine}.{extension}"

    subprocess.check_call(["wget", f"https://golang.org/dl/{file_name}"])

    if system != "windows":
        if not os.path.exists(out_path):
            os.makedirs(out_path)
        subprocess.check_call(["tar", "-C", out_path, "-xzf", file_name])
    else:
        subprocess.check_call(["msiexec", "/i", file_name, "/quiet"])


if __name__ == "__main__":
    go_get_go()
