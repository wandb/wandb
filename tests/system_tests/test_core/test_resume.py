from __future__ import annotations

import numpy as np
import pytest
import wandb
import wandb.errors
from wandb.sdk.lib import runid


@pytest.mark.parametrize("resume", ("allow", "never"))
def test_resume__no_run__success(user, resume):
    _ = user  # Create a fake user for the test.

    with wandb.init(resume=resume, id=runid.generate_id()) as run:
        pass

    assert not run.resumed


def test_resume_must__no_run__raises(user):
    _ = user  # Create a fake user for the test.

    with pytest.raises(wandb.errors.UsageError):
        wandb.init(resume="must", project="project")


@pytest.mark.parametrize("resume", ("allow", "must"))
def test_resume__run_exists__success(wandb_backend_spy, resume):
    with wandb.init() as run:
        run.log({"acc": 10}, step=15)
    with wandb.init(resume=resume, id=run.id) as run:
        run.log({"acc": 15})

    assert run.resumed
    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert history[0]["_step"] == 15
        assert history[1]["_step"] == 16


def test_resume_never__run_exists__raises(user):
    _ = user  # Create a fake user for the test.

    with wandb.init() as run:
        pass

    with pytest.raises(wandb.errors.UsageError):
        with wandb.init(resume="never", id=run.id):
            pass


@pytest.mark.parametrize("resume", ("allow", "never", "must", True))
def test_resume__offline__warns(resume, mock_wandb_log):
    with wandb.init(mode="offline", resume=resume):
        pass

    mock_wandb_log.assert_warned(
        "`resume` will be ignored since W&B syncing is set to `offline`"
    )


def test_resume_runtime_calculation(user, wandb_backend_spy):
    """
    This test is used to verify that the runtime is calculated correctly for a
    run that is resumed.
    """
    run_id = runid.generate_id()

    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunResumeStatus"),
        gql.once(
            content={
                "data": {
                    "model": {
                        "entity": {"name": f"{user}"},
                        "bucket": {
                            "name": run_id,
                            "config": "{}",
                            "historyLineCount": 0,
                            "eventsLineCount": 0,
                            "logLineCount": 0,
                            "eventsTail": "[]",
                            "historyTail": "[]",
                            "summaryMetrics": '{"_wandb": {"runtime": 130}}',  # injected runtime
                            "wandbConfig": '{"t": 1}',  # required to check that the run exists
                        },
                    },
                }
            },
            status=200,
        ),
    )

    with wandb.init(id=run_id, resume="must", project="runtime") as run:
        assert run._start_runtime == 130


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

    run = wandb.init(
        id=run_id,
        resume="must",
        project="tags",
        settings=test_settings(),
    )
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


def test_resume_config_preserves_image_mask(user, wandb_backend_spy):
    img_array = np.zeros((2, 2, 3), dtype=np.uint8)
    mask_array = np.zeros((1, 1), dtype=np.uint8)
    mask_array[0, 0] = 1
    class_labels = {1: "square"}

    with wandb.init() as run:
        run.log(
            {
                "test_image": wandb.Image(
                    img_array,
                    masks={
                        "prediction": {
                            "mask_data": mask_array,
                            "class_labels": class_labels,
                        }
                    },
                )
            }
        )

    with wandb.init(id=run.id, resume="must") as run:
        run.log(
            {
                "test_image_after_resume": wandb.Image(
                    img_array,
                    masks={
                        "prediction": {
                            "mask_data": mask_array,
                            "class_labels": class_labels,
                        }
                    },
                )
            }
        )

    with wandb_backend_spy.freeze() as snapshot:
        resumed_config = snapshot.config(run_id=run.id)
        class_labels = resumed_config["_wandb"]["value"]["mask/class_labels"]

        assert "test_image_wandb_delimeter_prediction" in class_labels
        assert "test_image_after_resume_wandb_delimeter_prediction" in class_labels


def test_resume_run_with_notes(user):
    notes = "do re mi fa sol la si"
    with wandb.init(project="notes", notes=notes) as run:
        run_id = run.id

    with wandb.init(id=run_id, resume="must", project="notes") as run:
        assert run.notes == notes


def test_resume_overwrite_notes(user):
    notes = "do re mi fa sol la si"
    with wandb.init(project="notes", notes=notes) as run:
        run_id = run.id

    new_notes = "c d e f g a b"
    with wandb.init(id=run_id, resume="must", project="notes", notes=new_notes) as run:
        assert run.notes == new_notes


def test_run_resumed__with_different_active_run(user):
    run_1 = wandb.init()
    run_1.config.update({"fruit": "banana"})
    run_1.finish()
    run_2 = wandb.init()
    run_2.config.update({"fruit": "apple"})

    with pytest.raises(wandb.Error):
        wandb.init(id=run_1.id, resume="must")


def test_run_resumed__with_different_active_run_explicitly_allow(user):
    run_1 = wandb.init()
    run_1.config.update({"fruit": "banana"})
    run_1.finish()
    run_2 = wandb.init()
    run_2.config.update({"fruit": "apple"})
    run_3 = wandb.init(id=run_1.id, resume="must", reinit="create_new")
    run_2.finish()
    run_3.finish()

    assert run_1.id == run_3.id
    assert run_3.resumed is True
    assert run_3.config.fruit == "banana"


def test_run_resumed__with_different_active_run_finished_previous(user):
    run_1 = wandb.init()
    run_1.config.update({"fruit": "banana"})
    run_1.finish()
    run_2 = wandb.init()
    run_2.config.update({"fruit": "apple"})
    run_2.finish()

    run_3 = wandb.init(id=run_1.id, resume="must", reinit="create_new")
    run_3.finish()

    assert run_1.id == run_3.id
    assert run_3.resumed is True
    assert run_3.config.fruit == "banana"
