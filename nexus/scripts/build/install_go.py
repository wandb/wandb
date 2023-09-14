import os
import platform
import subprocess

VERSION = "1.21.1"


def go_get_go():
    system = platform.system().lower()
    machine = platform.machine().lower().replace("x86_64", "amd64")
    extension = "tar.gz" if system != "windows" else "msi"
    out_path = "/usr/local" if system != "windows" else "C:\\Go"

    file_name = f"go{VERSION}.{system}-{machine}.{extension}"

    print(f"Downloading {file_name}")
    subprocess.check_call(
        [
            "curl",
            "-L",
            f"https://golang.org/dl/{file_name}",
            "-o",
            file_name,
        ]
    )

    if not os.path.exists(out_path):
        os.makedirs(out_path)

    if system != "windows":
        print(f"Extracting {file_name}")
        subprocess.check_call(["tar", "-C", out_path, "-xzf", file_name])
    else:
        print(f"Installing {file_name}")
        subprocess.check_call(["msiexec", "/i", file_name, "/quiet"])


if __name__ == "__main__":
    go_get_go()
