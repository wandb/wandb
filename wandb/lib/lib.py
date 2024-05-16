import ctypes
import pathlib
import platform
from typing import Optional


class Lib:
    def __init__(self) -> None:
        self._lib: Optional[ctypes.CDLL] = None

    @property
    def lib(self) -> ctypes.CDLL:
        if self._lib is not None:
            return self._lib
        dylib_ext = "dll" if platform.system().lower() == "windows" else "so"
        path_lib = (
            pathlib.Path(__file__).parent.parent / "bin" / f"libwandb.{dylib_ext}"
        )
        self._lib = ctypes.CDLL(str(path_lib))
        return self._lib

    def setup(self, core_path: str) -> str:
        self.lib.Setup.argtypes = [ctypes.c_char_p]
        self.lib.Setup.restype = ctypes.c_char_p
        address = self.lib.Setup(core_path.encode())
        return address.decode()

    def teardown(self, exit_code: int) -> None:
        self.lib.Teardown.argtypes = [ctypes.c_int]
        self.lib.Teardown(exit_code)


class Session:
    def __init__(self) -> None:
        self._lib = Lib()
        self.address = ""
        self._setup()

    def __enter__(self) -> "Session":
        self._setup()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO: make sure to call teardown with the right exit code
        self.teardown(0)

    def __del__(self) -> None:
        self.teardown(0)

    def _setup(self) -> None:
        core_path = str(pathlib.Path(__file__).parent.parent / "bin" / "wandb-core")
        self.address = self._lib.setup(core_path)

    def teardown(self, exit_code: int) -> None:
        self._lib.teardown(exit_code)
        self.address = ""
