import argparse
import pytest
import os
import sys
import os
import textwrap
import yaml

import wandb


@pytest.fixture
def wandb_init_run(tmpdir):
	"""Fixture that calls wandb.init(), yields the run that
	gets created, then cleans up afterward.
	"""
	# save the environment so we can restore it later. pytest
	# may actually do this itself. didn't check.
	orig_environ = dict(os.environ)
	try:
		os.environ['WANDB_MODE'] = 'clirun'  # no i/o wrapping - it breaks pytest
		os.environ['WANDB_PROJECT'] = 'unit-test-project'
		os.environ['WANDB_RUN_DIR'] = str(tmpdir)

		assert wandb.run is None
		assert wandb.config is None
		orig_namespace = vars(wandb)

		run = wandb.init()
		assert run is wandb.run
		assert run.config is wandb.config
		yield run

		wandb.uninit()
		assert vars(wandb) == orig_namespace
	finally:
		# restore the original environment
		os.environ.clear()
		os.environ.update(orig_environ)


def test_log(wandb_init_run):
	history_row = {'stuff': 5}
	wandb.log(history_row)
	assert len(wandb.run.history.rows) == 1
	assert set(history_row.items()) <= set(wandb.run.history.rows[0].items())