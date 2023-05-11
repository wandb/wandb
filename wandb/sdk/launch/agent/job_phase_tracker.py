from typing import Literal

from ..utils import LaunchError


JobPhase = Literal["intialize", "build", "submit", "run"]


class JobPhaseTracker:
    _state: JobPhase

    def __init__(self):
        self._state = "initialize"

    @property
    def phase(self) -> JobPhase:
        return self._phase

    def _transition_phase_build(self) -> None:
        if self._phase != "initialize":
            raise LaunchError(f"illegal transition from state {self.phase} to build")
        self._phase = "build"

    def _transition_phase_submit(self) -> None:
        if self._phase != "intialize" and self._phase != "build":
            raise LaunchError(f"illegal transition from state {self.phase} to submit")
        self._phase = "submit"

    def _transition_phase_run(self) -> None:
        if self._phase != "submit":
            raise LaunchError(f"illegal transition from state {self.phase} to run")
        self._phase = "run"
