import pytest
import wandb


def test_resume_tags_overwrite(user, test_settings):
    run = wandb.init(project="tags", tags=["tag1", "tag2"], settings=test_settings())
    run.tags += ("tag3",)
    run_id = run.id
    run.finish()

    run = wandb.init(
        id=run_id,
        resume="must",
        project="tags",
        tags=["tag4", "tag5"],
        settings=test_settings(),
    )
    run.tags += ("tag7",)
    assert run.tags == ("tag4", "tag5", "tag7")
    run.finish()


def test_resume_tags_preserve(user, test_settings):
    run = wandb.init(project="tags", tags=["tag1", "tag2"], settings=test_settings())
    run.tags += ("tag3",)
    run_id = run.id
    run.finish()

    run = wandb.init(id=run_id, resume="must", project="tags", settings=test_settings())
    run.tags += ("tag7",)
    assert run.tags == ("tag1", "tag2", "tag3", "tag7")
    run.finish()


def test_resume_tags_add_after_resume(user, test_settings):
    run = wandb.init(project="tags", settings=test_settings())
    run_id = run.id
    run.finish()

    run = wandb.init(id=run_id, resume="must", project="tags", settings=test_settings())
    run.tags += ("tag7",)
    assert run.tags == ("tag7",)
    run.finish()


def test_resume_tags_add_at_resume(user, test_settings):
    run = wandb.init(project="tags", settings=test_settings())
    run_id = run.id
    run.finish()

    run = wandb.init(
        id=run_id,
        resume="must",
        project="tags",
        tags=["tag4", "tag5"],
        settings=test_settings(),
    )
    run.tags += ("tag7",)
    assert run.tags == ("tag4", "tag5", "tag7")
    run.finish()


@pytest.mark.wandb_core_only
def test_resume_output_log(wandb_backend_spy):
    with wandb.init(
        project="output",
        settings=wandb.Settings(
            console="auto",
            console_multipart=True,
        ),
    ) as run:
        run_id = run.id
        print(f"started {run_id}")

    with wandb.init(
        id=run_id,
        resume="must",
        project="output",
        settings=wandb.Settings(
            console="auto",
            console_multipart=True,
        ),
    ) as run:
        print(f"resumed {run_id}")
        run.log({"metric": 1})

    with wandb_backend_spy.freeze() as snapshot:
        # should produce two files, e.g.:
        # logs/output_20240522_144304_516302.log and
        # logs/output_20240522_144306_374584.log
        log_files = [
            f
            for f in snapshot.uploaded_files(run_id=run_id)
            if f.startswith("logs/output_") and f.endswith(".log")
        ]
        assert len(log_files) == 2
