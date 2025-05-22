#
"""InternalRun - Internal-only run object.

Semi-stubbed run for internal process use.

"""

from typing_extensions import override

from wandb.sdk import wandb_run


class InternalRun(wandb_run.Run):
    def __init__(self, run_obj, settings, datatypes_cb):
        super().__init__(settings=settings)
        self._run_obj = run_obj
        self._datatypes_cb = datatypes_cb

    @override
    def _set_backend(self, backend):
        # This type of run object can't have a backend
        # or do any writes.
        pass

    @override
    def _publish_file(self, fname: str) -> None:
        self._datatypes_cb(fname)
