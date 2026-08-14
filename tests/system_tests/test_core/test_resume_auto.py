import json
import pathlib

import pytest
import wandb


class AutoResumeTestError(Exception):
    """Raised in auto-resume tests to leave behind an auto-resume file."""


def test_autoresume_first_run_saves(wandb_backend_spy):
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="online", resume="auto") as run:
            raise AutoResumeTestError()

    resume_path = pathlib.Path(run.settings.resume_fname)
    assert resume_path.exists()
    assert json.loads(resume_path.read_text())["run_id"] == run.id


def test_autoresume_second_run_loads(wandb_backend_spy):
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="online", resume="auto") as run1:
            raise AutoResumeTestError()

    with wandb.init(mode="online", resume="auto") as run2:
        pass

    assert run2.id == run1.id


def test_explicit_id_overrides_autoresume(wandb_backend_spy, mock_wandb_log):
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="online", resume="auto") as run1:
            raise AutoResumeTestError()

    with wandb.init(mode="online", resume="auto", id="auto-id") as run2:
        pass

    assert run2.id == "auto-id"
    mock_wandb_log.assert_warned(
        f"Ignoring ID {run1.id} loaded due to resume='auto'"
        f" because the run ID is set to auto-id."
    )


def test_autoresume_bad_format(wandb_backend_spy):
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="online", resume="auto") as run1:
            raise AutoResumeTestError()
    pathlib.Path(run1.settings.resume_fname).write_text("not JSON")

    with wandb.init(mode="online", resume="auto") as run2:
        pass

    assert run2.id != run1.id


def test_autoresume_no_id(wandb_backend_spy):
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="online", resume="auto") as run1:
            raise AutoResumeTestError()
    pathlib.Path(run1.settings.resume_fname).write_text(r"{}")

    with wandb.init(mode="online", resume="auto") as run2:
        pass

    assert run2.id != run1.id
