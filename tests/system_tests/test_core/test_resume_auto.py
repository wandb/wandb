import pathlib

import pytest
import wandb


class AutoResumeTestError(Exception):
    """Raised in auto-resume tests to leave behind an auto-resume file."""


def test_autoresume_offline_does_not_save():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run:
            raise AutoResumeTestError()

    resume_path = pathlib.Path(run.settings.resume_fname)
    assert not resume_path.exists()


def test_autoresume_offline_does_not_load():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run1:
            raise AutoResumeTestError()
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run2:
            raise AutoResumeTestError()

    resume_path = pathlib.Path(run2.settings.resume_fname)
    assert not resume_path.exists()
    assert run2.id != run1.id


def test_explicit_id_offline_ignores_autoresume_file():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto", id="auto-id"):
            raise AutoResumeTestError()
    with wandb.init(mode="offline", resume="auto", id="explicit") as run2:
        pass

    assert run2.id == "explicit"


def test_autoresume_bad_format():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run1:
            raise AutoResumeTestError()
    pathlib.Path(run1.settings.resume_fname).write_text("not JSON")

    with wandb.init(mode="offline", resume="auto") as run2:
        pass

    assert run2.id != run1.id


def test_autoresume_no_id():
    with pytest.raises(AutoResumeTestError):
        with wandb.init(mode="offline", resume="auto") as run1:
            raise AutoResumeTestError()
    pathlib.Path(run1.settings.resume_fname).write_text(r"{}")

    with wandb.init(mode="offline", resume="auto") as run2:
        pass

    assert run2.id != run1.id
