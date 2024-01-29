import unittest

from wandb.apis.importers.internals.config import Namespace
from wandb.apis.importers.wandb import WandbImporter


def test_import_runs(request, server_src, user, user2):
    project_name = "test"

    importer = WandbImporter(
        src_base_url=request.config.wandb_server_settings.base_url,
        src_api_key=user,
        dst_base_url=request.config.wandb_server_settings2.base_url,
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


# def test_import_artifact_sequences(request, server_src, user2, user):
#     project_name = "test"

#     importer = WandbImporter(
#         src_base_url=request.config.wandb_server_settings.base_url,
#         src_api_key=user,
#         dst_base_url=request.config.wandb_server_settings2.base_url,
#         dst_api_key=user2,
#     )

#     importer.import_artifact_sequences(
#         namespaces=[Namespace(user, project_name)],
#         remapping={Namespace(user, project_name): Namespace(user2, project_name)},
#     )

#     src_arts = list(
#         importer.src_api.artifacts("logged_art", f"{user}/{project_name}/logged_art")
#     )
#     dst_arts = list(
#         importer.dst_api.artifacts("logged_art", f"{user2}/{project_name}/logged_art")
#     )

#     assert len(src_arts) == 1
#     assert len(src_arts) == len(dst_arts)


def test_import_reports(request, server_src, user, user2):
    project_name = "test"

    importer = WandbImporter(
        src_base_url=request.config.wandb_server_settings.base_url,
        src_api_key=user,
        dst_base_url=request.config.wandb_server_settings2.base_url,
        dst_api_key=user2,
    )

    with unittest.mock.patch("wandb.sdk.lib.apikey.write_key"):
        importer.import_reports(
            namespaces=[Namespace(user, project_name)],
            remapping={Namespace(user, project_name): Namespace(user2, project_name)},
        )

    src_reports = [p for p in importer.src_api.reports(f"{user}/{project_name}")]
    dst_reports = [p for p in importer.dst_api.reports(f"{user2}/{project_name}")]

    assert len(src_reports) == 5
    assert len(src_reports) == len(dst_reports)
