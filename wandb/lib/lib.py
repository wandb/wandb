import ctypes
import pathlib
import platform
from typing import Optional


class Lib:
    def __init__(self) -> None:
        """Load the libwandb shared library.

        This class is a wrapper around the libwandb shared library. It loads the
        shared library and sets up the function signatures. The shared library
        is expected to be in the `wandb/bin` directory.
        """
        self._lib: Optional[ctypes.CDLL] = None
        self.init_sentry()

    @property
    def lib(self) -> ctypes.CDLL:
        """Load the shared library."""
        if self._lib is not None:
            return self._lib
        dylib_ext = "dll" if platform.system().lower() == "windows" else "so"
        path_lib = (
            pathlib.Path(__file__).parent.parent / "bin" / f"libwandb.{dylib_ext}"
        )
        self._lib = ctypes.CDLL(str(path_lib))

        # set up the function signatures
        self._lib.Setup.argtypes = [ctypes.c_char_p]
        self._lib.Setup.restype = ctypes.c_char_p
        self._lib.Teardown.argtypes = [ctypes.c_int]
        self._lib.LogPath.restype = ctypes.c_char_p

        return self._lib

    def setup(self, core_path: str) -> str:
        address = self.lib.Setup(core_path.encode())
        return address.decode()

    def teardown(self, exit_code: int) -> None:
        self.lib.Teardown(exit_code)

    def init_sentry(self) -> None:
        self.lib.InitSentry()

    def log_path(self) -> str:
        return self.lib.LogPath().decode()


class Session:
    def __init__(self) -> None:
        self._lib = Lib()
        self.address = ""
        self.log_path = ""
        self._setup()

    def __enter__(self) -> "Session":
        self._setup()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO: make sure to call teardown with the right exit code
        self.teardown(0)

    def __del__(self) -> None:
        try:
            self.teardown(0)
        except Exception:
            pass

    def _setup(self) -> None:
        core_path = str(pathlib.Path(__file__).parent.parent / "bin" / "wandb-core")
        self.address = self._lib.setup(core_path)
        self.log_path = self._lib.log_path()

    def teardown(self, exit_code: int) -> None:
        self._lib.teardown(exit_code)
        self.address = ""
        self.log_path = ""
