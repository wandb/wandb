from __future__ import annotations

import unittest

import pytest
from wandb.apis.importers import Namespace
from wandb.apis.importers.wandb import WandbImporter


@pytest.mark.xfail(reason="TODO: Breaks on server > 0.57.4")
def test_import_runs(
    local_wandb_backend,
    local_wandb_backend_importers,
    server_src,
    user,
    user2,
):
    project_name = "test"

    for _ in range(3):
        importer = WandbImporter(
            src_base_url=local_wandb_backend.base_url,
            src_api_key=user,
            dst_base_url=local_wandb_backend_importers.base_url,
            dst_api_key=user2,
        )

        importer.import_runs(
            namespaces=[Namespace(user, project_name)],
            remapping={Namespace(user, project_name): Namespace(user2, project_name)},
        )

        src_runs = sorted(
            importer.src_api.runs(f"{user}/{project_name}"), key=lambda r: r.name
        )
        dst_runs = sorted(
            importer.dst_api.runs(f"{user2}/{project_name}"), key=lambda r: r.name
        )

        # We recreated the same runs
        assert len(src_runs) == 2
        assert len(src_runs) == len(dst_runs)

        # And the data is the same
        for src_run, dst_run in zip(src_runs, dst_runs):
            src_history = list(src_run.scan_history())
            dst_history = list(dst_run.scan_history())

            assert len(src_history) == len(dst_history)
            for src_row, dst_row in zip(src_history, dst_history):
                assert src_row == dst_row


@pytest.mark.skip(reason="This test is flaking")
def test_import_artifact_sequences(
    local_wandb_backend,
    local_wandb_backend_importers,
    server_src,
    user,
    user2,
):
    project_name = "test"

    # Run multiple times to check incremental import logic
    for _ in range(3):
        importer = WandbImporter(
            src_base_url=local_wandb_backend.base_url,
            src_api_key=user,
            dst_base_url=local_wandb_backend_importers.base_url,
            dst_api_key=user2,
        )

        # Mock only required because there is no great way to download files
        # in the test like there is for artifacts
        with unittest.mock.patch("wandb.apis.public.files.File.download"):
            importer.import_artifact_sequences(
                namespaces=[Namespace(user, project_name)],
                remapping={
                    Namespace(user, project_name): Namespace(user2, project_name)
                },
            )

        src_arts = sorted(
            importer.src_api.artifacts(
                "logged_art", f"{user}/{project_name}/logged_art"
            ),
            key=lambda art: art.name,
        )
        dst_arts = sorted(
            importer.dst_api.artifacts(
                "logged_art", f"{user2}/{project_name}/logged_art"
            ),
            key=lambda art: art.name,
        )

        # We re-created the artifacts
        assert len(src_arts) == 4  # = 2 arts * 2 runs
        assert len(src_arts) == len(dst_arts)

        # Their contents are the same
        for src_art, dst_art in zip(src_arts, dst_arts):
            assert src_art.name == dst_art.name
            assert src_art.type == dst_art.type
            assert src_art.digest == dst_art.digest

            # Down to the individual manifest entries
            assert src_art.manifest.entries.keys() == dst_art.manifest.entries.keys()
            for name in src_art.manifest.entries.keys():
                src_entry = src_art.manifest.entries[name]
                dst_entry = dst_art.manifest.entries[name]

                assert src_entry.path == dst_entry.path
                assert src_entry.digest == dst_entry.digest
                assert src_entry.size == dst_entry.size


def test_import_reports(
    local_wandb_backend,
    local_wandb_backend_importers,
    server_src,
    user,
    user2,
):
    project_name = "test"

    for _ in range(3):
        importer = WandbImporter(
            src_base_url=local_wandb_backend.base_url,
            src_api_key=user,
            dst_base_url=local_wandb_backend_importers.base_url,
            dst_api_key=user2,
        )

        importer.import_reports(
            namespaces=[Namespace(user, project_name)],
            remapping={Namespace(user, project_name): Namespace(user2, project_name)},
        )

        src_reports = [p for p in importer.src_api.reports(f"{user}/{project_name}")]
        dst_reports = [p for p in importer.dst_api.reports(f"{user2}/{project_name}")]

        assert len(src_reports) == 2
        assert len(src_reports) == len(dst_reports)
