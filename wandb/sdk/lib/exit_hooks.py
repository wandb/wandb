import sys
import traceback
from types import TracebackType
from typing import TYPE_CHECKING, Optional, Type

import wandb
from wandb.errors import Error

if TYPE_CHECKING:
    from typing import NoReturn


class ExitHooks:
    exception: Optional[BaseException] = None

    def __init__(self) -> None:
        self.exit_code = 0
        self.exception = None

    def hook(self) -> None:
        self._orig_exit = sys.exit
        sys.exit = self.exit
        self._orig_excepthook = (
            sys.excepthook
            if sys.excepthook
            != sys.__excepthook__  # respect hooks by other libraries like pdb
            else None
        )
        sys.excepthook = self.exc_handler  # type: ignore

    def exit(self, code: object = 0) -> "NoReturn":
        orig_code = code
        code = code if code is not None else 0
        code = code if isinstance(code, int) else 1
        self.exit_code = code
        self._orig_exit(orig_code)  # type: ignore

    def was_ctrl_c(self) -> bool:
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(
        self, exc_type: Type[BaseException], exc: BaseException, tb: TracebackType
    ) -> None:
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            wandb.termerror(str(exc), repeat=False)

        if self.was_ctrl_c():
            self.exit_code = 255

        traceback.print_exception(exc_type, exc, tb)
        if self._orig_excepthook:
            self._orig_excepthook(exc_type, exc, tb)
