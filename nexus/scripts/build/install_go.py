import platform
import subprocess

VERSION = "1.21.1"


def go_get_go():
    system = platform.system().lower()
    machine = platform.machine().lower().replace("x86_64", "amd64")
    extension = "tar.gz" if system != "windows" else "zip"

    file_name = f"go{VERSION}.{system}-{machine}.{extension}"

    subprocess.check_call(
        ["wget", f"https://golang.org/dl/{file_name}"]
    )

    if system != "windows":
        subprocess.check_call(
            ["tar", "-C", "/usr/local", "-xzf", file_name]
        )
    else:
        subprocess.check_call(
            ["unzip", file_name, "-d", "/usr/local"]
        )


if __name__ == "__main__":
    go_get_go()
