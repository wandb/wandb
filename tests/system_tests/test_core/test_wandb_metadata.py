import pytest
import wandb


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.wandb_core_only
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

    # reading metadata should return the updated values
    assert run._metadata.email == "sus@wandb.ai"
    assert run._metadata.cpu_count == 1337
    assert run._metadata.gpu_count == 420

    run.finish()


@pytest.mark.skip_wandb_core
def test_metadata_legacy(user):
    run = wandb.init()

    # Legacy service does not support metadata
    assert run._metadata is None
    run.finish()
