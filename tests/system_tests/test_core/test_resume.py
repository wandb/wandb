import numpy as np
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
    img_array = np.zeros((100, 100, 3), dtype=np.uint8)
    mask_array = np.zeros((100, 100), dtype=np.uint8)
    mask_array[30:70, 30:70] = 1
    class_labels = {1: "square"}

    with wandb.init(project="config_preservation") as run:
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

        run_id = run.id
        run.finish()

    # Verify the config from the initial run
    with wandb_backend_spy.freeze() as snapshot:
        config = snapshot.config(run_id=run_id)
        assert "_wandb" in config
        wandb_config = config["_wandb"]["value"]

        item_config = wandb_config.get("mask/class_labels", {})
        initial_item_keys = set(item_config.keys())
        assert len(initial_item_keys) > 0

    # Resume the run
    with wandb.init(
        id=run_id,
        resume="must",
        project="config_preservation",
    ) as run:
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

    # Validate config after resuming and adding another item
    with wandb_backend_spy.freeze() as snapshot:
        resumed_config = snapshot.config(run_id=run_id)
        assert "_wandb" in resumed_config
        resumed_wandb_config = resumed_config["_wandb"]["value"]

        resumed_item_config = resumed_wandb_config.get("mask/class_labels", {})
        resumed_item_keys = set(resumed_item_config.keys())

        # Verify that all original keys are preserved
        assert initial_item_keys.issubset(resumed_item_keys)

        # Verify that we have new keys
        new_keys = resumed_item_keys - initial_item_keys
        assert len(new_keys) > 0
