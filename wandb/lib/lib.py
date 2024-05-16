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

    def setup(self, core_path: str) -> None:
        self.lib.Setup(core_path.encode())

    def teardown(self) -> None:
        self.lib.Teardown()


class Session:
    def __init__(self) -> None:
        self._lib = Lib()
        self._setup()

    def __enter__(self) -> "Session":
        self._setup()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.teardown()

    def __del__(self) -> None:
        self.teardown()

    def _setup(self) -> None:
        core_path = str(pathlib.Path(__file__).parent.parent / "bin" / "wandb-core")
        self._lib.setup(core_path)

    def teardown(self) -> None:
        self._lib.teardown()
