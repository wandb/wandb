from typing import Optional

from wandb.sdk.launch.sweeps.scheduler import Scheduler, SweepRun


class NoopScheduler(Scheduler):
    """A custom scheduler that does nothing."""

    def _get_next_sweep_run(self, worker_id: int) -> Optional[SweepRun]:
        self.stop_sweep()
        return None

    def _poll(self) -> None:
        pass

    def _exit(self) -> None:
        pass

    def _save_state(self) -> None:
        pass

    def _load_state(self) -> None:
        pass


"""
NoopScheduler sweep config:

method: custom
job: <JOB>
custom:
   type: noop

"""
