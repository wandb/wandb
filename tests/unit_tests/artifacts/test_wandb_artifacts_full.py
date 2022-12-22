import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import wandb
from wandb import wandb_sdk
from wandb.errors import WaitTimeoutError

sm = wandb.wandb_sdk.internal.sender.SendManager


def test_add_table_from_dataframe(wandb_init):

    import pandas as pd

    df_float = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float_)
    df_float32 = pd.DataFrame([[1, 2.0, 3.0]], dtype=np.float32)
    df_bool = pd.DataFrame([[True, False, True]], dtype=np.bool_)

    current_time = datetime.now()
    df_timestamp = pd.DataFrame(
        [[current_time + timedelta(days=i)] for i in range(10)], columns=["date"]
    )

    wb_table_float = wandb.Table(dataframe=df_float)
    wb_table_float32 = wandb.Table(dataframe=df_float32)
    wb_table_float32_recast = wandb.Table(dataframe=df_float32.astype(np.float_))
    wb_table_bool = wandb.Table(dataframe=df_bool)
    wb_table_timestamp = wandb.Table(dataframe=df_timestamp)

    run = wandb_init()
    artifact = wandb.Artifact("table-example", "dataset")
    artifact.add(wb_table_float, "wb_table_float")
    artifact.add(wb_table_float32_recast, "wb_table_float32_recast")
    artifact.add(wb_table_float32, "wb_table_float32")
    artifact.add(wb_table_bool, "wb_table_bool")

    # check that timestamp is correctly converted to ms and not ns
    json_repr = wb_table_timestamp.to_json(artifact)
    assert "data" in json_repr and np.isclose(
        json_repr["data"][0][0],
        current_time.replace(tzinfo=timezone.utc).timestamp() * 1000,
    )
    artifact.add(wb_table_timestamp, "wb_table_timestamp")

    run.log_artifact(artifact)

    run.finish()


def test_artifact_error_for_invalid_aliases(wandb_init):

    run = wandb_init()
    artifact = wandb.Artifact("test-artifact", "dataset")
    error_aliases = [["latest", "workflow:boom"], ["workflow/boom/test"]]
    for aliases in error_aliases:
        with pytest.raises(ValueError) as e_info:
            run.log_artifact(artifact, aliases=aliases)
            assert (
                str(e_info.value)
                == "Aliases must not contain any of the following characters: /, :"
            )

    for aliases in [["latest", "boom_test-q"]]:
        run.log_artifact(artifact, aliases=aliases)

    run.finish()


def test_artifact_upsert_no_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Upsert without a group or id should fail
    run = wandb_init()
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    with pytest.raises(TypeError):
        run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_group_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a group should succeed
    run = wandb_init(group=group_name)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_1")
    run.upsert_artifact(artifact)
    run.finish()


def test_artifact_upsert_distributed_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Upsert with a distributed_id should succeed
    run = wandb_init()
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    artifact.add(image, "image_2")
    run.upsert_artifact(artifact, distributed_id=group_name)
    run.finish()


def test_artifact_finish_no_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    artifact_type = "dataset"

    # Finish without a distributed_id should fail
    run = wandb_init()
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    with pytest.raises(TypeError):
        run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_group_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb_init(group=group_name)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact)
    run.finish()


def test_artifact_finish_distributed_id(wandb_init):

    # NOTE: these tests are against a mock server so they are testing the internal flows, but
    # not the actual data transfer.
    artifact_name = f"distributed_artifact_{round(time.time())}"
    group_name = f"test_group_{round(np.random.rand())}"
    artifact_type = "dataset"

    # Finish with a distributed_id should succeed
    run = wandb_init()
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    run.finish_artifact(artifact, distributed_id=group_name)
    run.finish()


# this test hangs, which seems to be the result of incomplete mocks.
# would be worth returning to it in the future
# def test_artifact_incremental( relay_server, parse_ctx, test_settings):
#
#         open("file1.txt", "w").write("hello")
#         run = wandb.init(settings=test_settings)
#         artifact = wandb.Artifact(type="dataset", name="incremental_test_PENDING", incremental=True)
#         artifact.add_file("file1.txt")
#         run.log_artifact(artifact)
#         run.finish()

#         manifests_created = parse_ctx(relay_server.get_ctx()).manifests_created
#         assert manifests_created[0]["type"] == "INCREMENTAL"


@pytest.mark.flaky
@pytest.mark.xfail(reason="flaky on CI")
def test_edit_after_add(wandb_init):
    artifact = wandb.Artifact(name="hi-art", type="dataset")
    filename = "file1.txt"
    open(filename, "w").write("hello!")
    artifact.add_file(filename)
    open(filename, "w").write("goodbye.")
    with wandb_init() as run:
        run.log_artifact(artifact)
        artifact.wait()
    with wandb_init() as run:
        art_path = run.use_artifact("hi-art:latest").download()

    # The file from the retrieved artifact should match the original.
    assert open(os.path.join(art_path, filename)).read() == "hello!"
    # While the local file should have the edit applied.
    assert open(filename).read() == "goodbye."


def test_uploaded_artifacts_are_unstaged(wandb_init, tmp_path, monkeypatch):
    # Use a separate staging directory for the duration of this test.
    monkeypatch.setenv("WANDB_DATA_DIR", str(tmp_path))
    staging_dir = Path(wandb_sdk.interface.artifacts.get_staging_dir())

    def dir_size():
        return sum(f.stat().st_size for f in staging_dir.rglob("*") if f.is_file())

    artifact = wandb.Artifact(name="stage-test", type="dataset")
    with open("random.bin", "wb") as f:
        f.write(np.random.bytes(4096))
    artifact.add_file("random.bin")

    # The file is staged until it's finalized.
    assert dir_size() == 4096

    with wandb_init() as run:
        run.log_artifact(artifact)

    # The staging directory should be empty again.
    assert dir_size() == 0


def test_local_references(wandb_init):

    run = wandb_init()

    def make_table():
        return wandb.Table(columns=[], data=[])

    t1 = make_table()
    artifact1 = wandb.Artifact("test_local_references", "dataset")
    artifact1.add(t1, "t1")
    assert artifact1.manifest.entries["t1.table.json"].ref is None
    run.log_artifact(artifact1)
    artifact2 = wandb.Artifact("test_local_references_2", "dataset")
    artifact2.add(t1, "t2")
    assert artifact2.manifest.entries["t2.table.json"].ref is not None
    run.finish()


def test_artifact_wait_success(wandb_init):
    # Test artifact wait() timeout parameter
    timeout = 60
    leeway = 0.50
    run = wandb_init()
    artifact = wandb.Artifact("art", type="dataset")
    start_timestamp = time.time()
    run.log_artifact(artifact).wait(timeout=timeout)
    elapsed_time = time.time() - start_timestamp
    assert elapsed_time < timeout * (1 + leeway)
    run.finish()


@pytest.mark.parametrize("timeout", [0, 1e-6])
def test_artifact_wait_failure(wandb_init, timeout):
    # Test to expect WaitTimeoutError when wait timeout is reached and large image
    # wasn't uploaded yet
    image = wandb.Image(np.random.randint(0, 255, (10, 10)))
    run = wandb_init()
    with pytest.raises(WaitTimeoutError):
        artifact = wandb.Artifact("art", type="image")
        artifact.add(image, "image")
        run.log_artifact(artifact).wait(timeout=timeout)
    run.finish()
