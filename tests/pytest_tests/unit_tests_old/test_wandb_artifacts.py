from typing import Callable

import numpy as np
import pytest
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError


@pytest.mark.timeout(120)
def test_artifact_log_with_network_error(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        run = wandb.init(settings=test_settings)
        artifact = wandb.Artifact("table-example", "dataset")
        live_mock_server.set_ctx({"fail_graphql_times": 15})
        run.log_artifact(artifact)
        live_mock_server.set_ctx({"fail_graphql_times": 0})
        run.finish()


def test_artifact_references_internal(
    runner,
    mocked_run,
    mock_server,
    internal_sm,
    backend_interface,
    parse_ctx,
    test_settings,
):
    with runner.isolated_filesystem():
        mock_server.set_context("max_cli_version", "0.11.0")
        run = wandb.init(settings=test_settings)
        t1 = wandb.Table(columns=[], data=[])
        art = wandb.Artifact("A", "dataset")
        art.add(t1, "t1")
        run.log_artifact(art)
        run.finish()

        art = wandb.Artifact("A_PENDING", "dataset")
        art.add(t1, "t1")

        with backend_interface() as interface:
            proto_run = interface._make_run(mocked_run)
            internal_sm.send_run(interface._make_record(run=proto_run))

            proto_artifact = interface._make_artifact(art)
            proto_artifact.run_id = proto_run.run_id
            proto_artifact.project = proto_run.project
            proto_artifact.entity = proto_run.entity
            proto_artifact.user_created = False
            proto_artifact.use_after_commit = False
            proto_artifact.finalize = True
            for alias in ["latest"]:
                proto_artifact.aliases.append(alias)
            log_artifact = pb.LogArtifactRequest()
            log_artifact.artifact.CopyFrom(proto_artifact)

            internal_sm.send_artifact(log_artifact)


@pytest.mark.timeout(300)
def test_lazy_artifact_passthrough(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        run = wandb.init(settings=test_settings)
        art = wandb.Artifact("test_lazy_artifact_passthrough", "dataset")

        t1 = wandb.Table(columns=[], data=[])
        e = art.add(t1, "t1")
        with pytest.raises(ValueError):
            e.ref_target()

        # These getters should be valid both before and after logging
        testable_getters_valid = [
            "id",
            "name",
            "source_name",
            "type",
            "description",
            "metadata",
            "distributed_id",
            "incremental",
            "use_as",
            "state",
            "manifest",
            "digest",
            "size",
        ]
        # These getters should be valid only after logging
        testable_getters_invalid = [
            "entity",
            "project",
            "qualified_name",
            "version",
            "source_entity",
            "source_project",
            "source_qualified_name",
            "source_version",
            "aliases",
            "commit_hash",
            "file_count",
            "created_at",
            "updated_at",
        ]

        # These setters should be valid both before and after logging
        testable_setters_valid = [
            "description",
            "metadata",
            "distributed_id",
        ]
        # These setters should be valid only after logging
        testable_setters_invalid = ["aliases"]
        setter_data = {"metadata": {}, "aliases": []}

        # These methods should be valid both before and after logging
        testable_methods_valid = ["finalize", "is_draft"]
        # These methods should be valid only after logging
        testable_methods_invalid = [
            "get_path",
            "get",
            "download",
            "checkout",
            "verify",
            "delete",
            "used_by",
            "logged_by",
            "json_encode",
        ]
        params = {"get_path": ["t1.table.json"], "get": ["t1"], "delete": [True]}
        # these are failures of mocking
        special_errors = {
            "verify": ValueError,
        }

        for valid_getter in testable_getters_valid:
            _ = getattr(art, valid_getter)
        for invalid_getter in testable_getters_invalid:
            with pytest.raises(ArtifactNotLoggedError):
                _ = getattr(art, invalid_getter)

        for valid_setter in testable_setters_valid:
            setattr(art, valid_setter, setter_data.get(valid_setter, valid_setter))
        for invalid_setter in testable_setters_invalid:
            with pytest.raises(ArtifactNotLoggedError):
                setattr(
                    art, invalid_setter, setter_data.get(invalid_setter, invalid_setter)
                )

        for valid_method in testable_methods_valid:
            attr_method = getattr(art, valid_method)
            _ = attr_method(*params.get(valid_method, []))
        for invalid_method in testable_methods_invalid:
            attr_method = getattr(art, invalid_method)
            with pytest.raises(ArtifactNotLoggedError):
                _ = attr_method(*params.get(invalid_method, []))

        # THE LOG
        run.log_artifact(art)

        for valid_getter in testable_getters_valid:
            _ = getattr(art, valid_getter)
        for invalid_getter in testable_getters_invalid:
            with pytest.raises(ArtifactNotLoggedError):
                _ = getattr(art, invalid_getter)

        for valid_setter in testable_setters_valid:
            setattr(art, valid_setter, setter_data.get(valid_setter, valid_setter))
        for invalid_setter in testable_setters_invalid:
            with pytest.raises(ArtifactNotLoggedError):
                setattr(
                    art, invalid_setter, setter_data.get(invalid_setter, invalid_setter)
                )

        for valid_method in testable_methods_valid:
            attr_method = getattr(art, valid_method)
            _ = attr_method(*params.get(valid_method, []))
        for invalid_method in testable_methods_invalid:
            attr_method = getattr(art, invalid_method)
            with pytest.raises(ArtifactNotLoggedError):
                _ = attr_method(*params.get(invalid_method, []))

        # THE ALL IMPORTANT WAIT
        art.wait()

        for getter in testable_getters_valid + testable_getters_invalid:
            _ = getattr(art, getter)

        for setter in testable_setters_valid + testable_setters_invalid:
            setattr(art, setter, setter_data.get(setter, setter))

        for method in testable_methods_valid + testable_methods_invalid:
            attr_method = getattr(art, method)
            if method in special_errors:
                with pytest.raises(special_errors[method]):
                    _ = attr_method(*params.get(method, []))
            else:
                _ = attr_method(*params.get(method, []))

        run.finish()


def test_reference_download(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        run = wandb.init(settings=test_settings)
        artifact = wandb.Artifact("test_reference_download", "dataset")
        artifact.add_file("file1.txt")
        artifact.add_reference(
            "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )
        run.log_artifact(artifact)
        run.finish()

        run = wandb.init(settings=test_settings)
        artifact = run.use_artifact("my-test_reference_download:latest")
        entry = artifact.get_path("StarWars3.wav")
        entry.download()
        assert (
            entry.ref_target()
            == "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )

        entry = artifact.get_path("file1.txt")
        entry.download()
        with pytest.raises(ValueError):
            assert entry.ref_target()
        run.finish()


def test_communicate_artifact(runner, publish_util, mocked_run):
    with runner.isolated_filesystem():
        artifact = wandb.Artifact("comms_test_PENDING", "dataset")
        artifact_publish = dict(run=mocked_run, artifact=artifact, aliases=["latest"])
        ctx_util = publish_util(artifacts=[artifact_publish])
        assert len(set(ctx_util.manifests_created_ids)) == 1


def _create_artifact_and_set_metadata(metadata):
    artifact = wandb.Artifact("foo", "dataset")
    artifact.metadata = metadata
    return artifact


# All these metadata-validation tests should behave identically
# regardless of whether we set the metadata by passing it into the constructor
# or by setting the attribute after creation; so, parametrize how we build the
# artifact, and run tests both ways.
@pytest.mark.parametrize(
    "create_artifact",
    [
        lambda metadata: wandb.Artifact("foo", "dataset", metadata=metadata),
        _create_artifact_and_set_metadata,
    ],
)
class TestArtifactChecksMetadata:
    def test_validates_metadata_ok(
        self, create_artifact: Callable[..., wandb.Artifact]
    ):
        assert create_artifact(metadata=None).metadata == {}
        assert create_artifact(metadata={"foo": "bar"}).metadata == {"foo": "bar"}
        assert create_artifact(
            metadata={"foo": {"bar": [1, 2, (3, None)]}}
        ).metadata == {"foo": {"bar": [1, 2, [3, None]]}}
        assert create_artifact(metadata={"foo": np.arange(3)}).metadata == {
            "foo": [0, 1, 2]
        }
        assert create_artifact(metadata={"foo": slice(4, 9, 2)}).metadata == {
            "foo": {"slice_start": 4, "slice_stop": 9, "slice_step": 2}
        }

    def test_validates_metadata_err(
        self, create_artifact: Callable[..., wandb.Artifact]
    ):
        with pytest.raises(TypeError):
            create_artifact(metadata=123)

        with pytest.raises(TypeError):
            create_artifact(metadata=[])

        with pytest.raises(TypeError):
            create_artifact(metadata={"unserializable": object()})

    def test_deepcopies_metadata(self, create_artifact: Callable[..., wandb.Artifact]):
        orig_metadata = {"foo": ["original"]}
        artifact = create_artifact(metadata=orig_metadata)

        # ensure `artifact.metadata` isn't just a reference to the argument
        assert artifact.metadata is not orig_metadata
        orig_metadata["bar"] = "modifying the top-level value"
        assert "bar" not in artifact.metadata

        # ensure that any mutable sub-values are also copies
        assert artifact.metadata["foo"] is not orig_metadata["foo"]
        orig_metadata["foo"].append("modifying the sub-value")
        assert artifact.metadata["foo"] == ["original"]
