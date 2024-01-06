"""port_file: write/read file containing port info."""

import os
import tempfile
from typing import Optional


class PortFile:
    _sock_port: Optional[int]
    _valid: bool

    SOCK_TOKEN = "sock="
    EOF_TOKEN = "EOF"

    def __init__(self, sock_port: Optional[int] = None) -> None:
        self._sock_port = sock_port
        self._valid = False

    def write(self, fname: str) -> None:
        dname, bname = os.path.split(fname)
        f = tempfile.NamedTemporaryFile(prefix=bname, dir=dname, mode="w", delete=False)
        try:
            tmp_filename = f.name
            with f:
                data = []
                if self._sock_port:
                    data.append(f"{self.SOCK_TOKEN}{self._sock_port}")
                data.append(self.EOF_TOKEN)
                port_str = "\n".join(data)
                written = f.write(port_str)
                assert written == len(port_str)
            os.rename(tmp_filename, fname)
        except Exception:
            os.unlink(tmp_filename)
            raise

    def read(self, fname: str) -> None:
        with open(fname) as f:
            lines = f.readlines()
            if lines[-1] != self.EOF_TOKEN:
                return
            for ln in lines:
                if ln.startswith(self.SOCK_TOKEN):
                    self._sock_port = int(ln[len(self.SOCK_TOKEN) :])
            self._valid = True

    @property
    def sock_port(self) -> Optional[int]:
        return self._sock_port

    @property
    def is_valid(self) -> bool:
        return self._valid
