import ctypes
import pathlib
import platform


class Lib:
    def __init__(self) -> None:
        dylib_ext = "dll" if platform.system().lower() == "windows" else "so"
        path_lib = (
            pathlib.Path(__file__).parent.parent / "bin" / f"libwandb.{dylib_ext}"
        )
        self.lib = ctypes.CDLL(str(path_lib))

    def init(self, run_id: str) -> None:
        self.lib.Init(run_id.encode())
