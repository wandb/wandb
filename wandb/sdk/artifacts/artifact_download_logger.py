"""Artifact download logger."""

import multiprocessing.dummy
import time
from typing import Callable

from wandb.errors.term import termlog


class ArtifactDownloadLogger:
    def __init__(
        self,
        nfiles: int,
        clock_for_testing: Callable[[], float] = time.monotonic,
        termlog_for_testing: Callable[..., None] = termlog,
    ) -> None:
        self._nfiles = nfiles
        self._clock = clock_for_testing
        self._termlog = termlog_for_testing

        self._n_files_downloaded = 0
        self._spinner_index = 0
        self._last_log_time = self._clock()
        self._lock = multiprocessing.dummy.Lock()

    def notify_downloaded(self) -> None:
        with self._lock:
            self._n_files_downloaded += 1
            if self._n_files_downloaded == self._nfiles:
                self._termlog(
                    f"  {self._nfiles} of {self._nfiles} files downloaded.  ",
                    # ^ trailing spaces to wipe out ellipsis from previous logs
                    newline=True,
                )
                self._last_log_time = self._clock()
            elif self._clock() - self._last_log_time > 0.1:
                self._spinner_index += 1
                spinner = r"-\|/"[self._spinner_index % 4]
                self._termlog(
                    f"{spinner} {self._n_files_downloaded} of {self._nfiles} files downloaded...\r",
                    newline=False,
                )
                self._last_log_time = self._clock()
