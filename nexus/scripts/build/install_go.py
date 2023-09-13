import subprocess

VERSION = "1.21.1"


def go_get_go():
    subprocess.check_call(
        ["wget", f"https://golang.org/dl/go{VERSION}.linux-amd64.tar.gz"]
    )
    subprocess.check_call(
        ["tar", "-C", "/usr/local", "-xzf", f"go{VERSION}.linux-amd64.tar.gz"]
    )
    subprocess.check_call(["rm", f"go{VERSION}.linux-amd64.tar.gz"])


if __name__ == "__main__":
    go_get_go()
