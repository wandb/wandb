"""Artifact download logger."""
import threading
import time
from typing import Callable


from wandb.errors.term import termlog


MAX_SECS_BETWEEN_DOWNLOAD = 3600 * 10

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
        self._last_download_time = self._clock()

        self._logging_thread = threading.Thread(target=self._logging_loop)
        self._logging_thread.daemon = True
        self._logging_thread.start()

    def _logging_loop(self):
        self._termlog(f"Kicking off new thread for logging management")
        last_download_progress = self._n_files_downloaded
        while self._n_files_downloaded < self._nfiles:
            if self._clock() - self._last_log_time > 0.1:
                self._spinner_index += 1
                spinner = r"-\|/"[self._spinner_index % 4]
                self._termlog(
                    f"{spinner} {self._n_files_downloaded} of {self._nfiles} files downloaded...\r",
                    newline=False,
                )
                self._last_log_time = self._clock()

            if last_download_progress != self._n_files_downloaded:
                self._last_download_time = self._clock()
                last_download_progress = self._n_files_downloaded
            elif self._clock() - self._last_download_time > MAX_SECS_BETWEEN_DOWNLOAD:
                self._termlog(
                    f"  Download is taking too long, aborting!  ",
                    newline=True,
                )
                break

    def notify_downloaded(self) -> None:
        self._n_files_downloaded += 1
