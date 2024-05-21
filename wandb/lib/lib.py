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

        return self._lib

    def setup(self, core_path: str) -> str:
        """Setup a new session.

        Setup a new session by starting the wandb-core service
        and establishing a connection to it.

        Args:
            core_path: Path to the wandb-core binary.

        Returns:
            The address of the session's wandb-core service.
        """
        address = self.lib.Setup(core_path.encode())
        return address.decode()

    def teardown(self, exit_code: int) -> None:
        """Teardown the session.

        Teardown the session by stopping the wandb-core service.

        Args:
            exit_code: The exit code to pass to the wand
                core service.
        """
        self.lib.Teardown(exit_code)

    def init_sentry(self) -> None:
        """Initialize the Sentry client."""
        self.lib.InitSentry()


class Session:
    def __init__(self) -> None:
        """Create a new session.

        The session is created by starting the wandb-core service
        and establishing a connection to it.

        This class can be used as a context manager. The session is torn
        down when the context manager exits.
        """
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
        try:
            self.teardown(0)
        except Exception:
            pass

    def _setup(self) -> None:
        """Setup the session."""
        core_path = str(pathlib.Path(__file__).parent.parent / "bin" / "wandb-core")
        self.address = self._lib.setup(core_path)

    def teardown(self, exit_code: int) -> None:
        """Teardown the session.

        Args:
            exit_code: The exit code to pass to the wandb-core service.
        """
        self._lib.teardown(exit_code)
        self.address = ""
