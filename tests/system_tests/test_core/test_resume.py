import numpy as np
import pytest
import wandb
from wandb.sdk.lib import runid


@pytest.mark.wandb_core_only
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
        print(f"started {run_id}")  # noqa: T201

    with wandb.init(
        id=run_id,
        resume="must",
        project="output",
        settings=wandb.Settings(
            console="auto",
            console_multipart=True,
        ),
    ) as run:
        print(f"resumed {run_id}")  # noqa: T201
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
