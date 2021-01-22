#
# -*- coding: utf-8 -*-
"""InternalRun - Internal-only run object.

Semi-stubbed run for internal process use.

"""
from wandb import data_types

from .. import wandb_run


class InternalRun(wandb_run.Run):
    def __init__(self, run_obj, settings, datatypes_cb):
        super(InternalRun, self).__init__(settings=settings)
        self._run_obj = run_obj

        # TODO: This overwrites what's done in the constructor of wandb_run.Run.
        # We really want a common interface for wandb_run.Run and InternalRun.
        data_types._datatypes_set_callback(datatypes_cb)

    def _set_backend(self, backend):
        # This type of run object can't have a backend
        # or do any writes.
        pass
