import pytest
import wandb


@pytest.mark.parametrize("disabled", [False, True])
def test_metadata_ops(user, disabled: bool):
    run = wandb.init(
        settings=wandb.Settings(
            mode="disabled" if disabled else "online",
            x_stats_sampling_interval=1,
        ),
    )

    # Run Metadata is stored in wandb-core.
    # run._metadata sends a request to wandb-core to get the metadata.

    # A RunStart request that happens during wandb.init() triggers
    # collection of metadata in wandb-core, therefore run._metadata
    # should not be None.
    assert run._metadata is not None
    if not disabled:
        assert run._metadata.email == f"{user}@wandb.com"
        assert run._metadata.cpu_count != 1337
        assert run._metadata.gpu_count is None

    # updating metadata will trigger an update in wandb-core
    run._metadata.email = "sus@wandb.ai"
    run._metadata.cpu_count = 1337
    run._metadata.gpu_count = 420

    # reading metadata again should return the updated values
    assert run._metadata.email == "sus@wandb.ai"
    assert run._metadata.cpu_count == 1337
    assert run._metadata.gpu_count == 420

    run.finish()


def test_metadata_access(user):
    with wandb.init() as run:
        run.log({"acc": 1})
        assert run._metadata is not None
        run._metadata.email = "lol@wandb.ai"
