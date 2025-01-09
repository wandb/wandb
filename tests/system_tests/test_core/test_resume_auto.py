import json
import pathlib

import pytest
import wandb


class AutoResumeTestError(Exception):
    """Raised in auto-resume tests to leave behind an auto-resume file."""


def test_autoresume_first_run_saves():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run:
            raise AutoResumeTestError()

    resume_path = pathlib.Path(run.settings.resume_fname)
    assert json.loads(resume_path.read_text()) == {"run_id": run.id}


def test_autoresume_second_run_loads():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run1:
            raise AutoResumeTestError()
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run2:
            raise AutoResumeTestError()

    resume_path = pathlib.Path(run2.settings.resume_fname)
    assert json.loads(resume_path.read_text()) == {"run_id": run1.id}


def test_explicit_id_overrides_autoresume():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto", id="auto-id"):
            raise AutoResumeTestError()
    with wandb.init(mode="offline", resume="auto", id="explicit") as run2:
        pass

    assert run2.id == "explicit"
