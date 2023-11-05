"""
test_wandb
----------------------------------

Tests for the `wandb.apis.PublicApi` module.
"""

import os

import pytest
import requests
import wandb
from wandb.old.summary import Summary
from wandb.sdk.lib import filesystem


def test_to_html(mock_server, api):
    run = api.from_path("test/test/test")
    assert "test/test/runs/test?jupyter=true" in run.to_html()
    sweep = api.from_path("test/test/sweeps/test")
    assert "test/test/sweeps/test?jupyter=true" in sweep.to_html()


def test_run_retry(mock_server, api):
    mock_server.set_context("fail_graphql_times", 2)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history_system(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {"cpu": 10},
        {"cpu": 20},
        {"cpu": 30},
    ]


def test_run_delete(mock_server, api):
    run = api.run("test/test/test")

    run.delete()
    variables = {"id": run.storage_id, "deleteArtifacts": False}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables

    run.delete(delete_artifacts=True)
    variables = {"id": run.storage_id, "deleteArtifacts": True}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables


def test_run_files(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.files()[0]
        file.download()
        assert os.path.exists("weights.h5")
        raised = False
        try:
            file.download()
        except wandb.CommError:
            raised = True
        assert raised


def test_run_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        file.download()
        assert os.path.exists("weights.h5")


def test_run_file_direct(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert (
            file.direct_url
            == "https://api.wandb.ai/storage?file=weights.h5&direct=true"
        )


def test_run_upload_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_run_upload_file_relative(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        filesystem.mkdir_exists_ok("foo")
        os.chdir("foo")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb", "../")
        assert file.url == "https://api.wandb.ai/storage?file=foo/new_file.pb"


def test_upload_file_retry(runner, mock_server, api):
    mock_server.set_context("fail_storage_count", 4)
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_upload_file_inject_retry(runner, mock_server, api, inject_requests):
    match = inject_requests.Match(path_suffix="/storage", count=2)
    inject_requests.add(
        match=match, requests_error=requests.exceptions.ConnectionError()
    )
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_runs_from_path(mock_server, api):
    runs = api.runs("test/test")
    assert len(runs) == 4
    list(runs)
    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}
    assert runs[0].group == "A"
    assert runs[0].job_type == "test"


def test_runs_from_path_index(mock_server, api):
    mock_server.set_context("page_times", 4)
    runs = api.runs("test/test")
    assert len(runs) == 4
    print(list(runs))
    assert runs[3]
    assert len(runs.objects) == 4


def test_projects(mock_server, api):
    projects = api.projects("test")
    # projects doesn't provide a length for now, so we iterate
    # them all to count
    count = 0
    for proj in projects:
        count += 1
    assert count == 2


def test_reports(mock_server, api):
    path = "test-entity/test-project"
    reports = api.reports(path)
    # calling __len__, __getitem__, or __next__ on a Reports object
    # triggers the actual API call to fetch data w/ pagination.
    length = len(reports)
    assert length == 1
    assert reports[0].description == "test-description"
    assert reports[0].pageCount == 0
    assert reports[1].pageCount == 1


def test_delete_file(runner, mock_server, api):
    run = api.run("test/test/test")
    file = run.files()[0]
    file.delete()

    assert mock_server.ctx["graphql"][-1]["variables"] == {"files": [file.id]}


def test_run_wait_until_finished(runner, mock_server, api, capsys):
    run = api.run("test/test/test")
    run.wait_until_finished()
    out, _ = capsys.readouterr()
    status = mock_server.ctx["run_state"]
    assert f"Run finished with status: {status}" in out


def test_query_team(mock_server, api):
    t = api.team("test")
    assert t.name == "test"
    assert t.members[0].account_type == "MEMBER"
    assert repr(t.members[0]) == "<Member test (MEMBER)>"


def test_viewer(mock_server, api):
    v = api.viewer
    assert v.admin is False
    assert v.username == "mock"
    assert v.api_keys == []
    assert v.teams == []


def test_create_service_account(mock_server, api):
    t = api.team("test")
    assert t.create_service_account("My service account").api_key == "Y" * 40
    mock_server.set_context("graphql_conflict", True)
    assert t.create_service_account("My service account") is None


def test_create_team(mock_server, api):
    t = api.create_team("test")
    assert t.name == "test"
    assert repr(t) == "<Team test>"


def test_create_team_exists(mock_server, api):
    mock_server.set_context("graphql_conflict", True)
    with pytest.raises(requests.exceptions.HTTPError):
        api.create_team("test")


def test_invite_user(mock_server, api):
    t = api.team("test")
    assert t.invite("test@test.com")
    assert t.invite("test")
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") is False


def test_delete_member(mock_server, api):
    t = api.team("test")
    assert t.members[0].delete()
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") is False


def test_query_user(mock_server, api):
    u = api.user("test@test.com")
    assert u.email == "test@test.com"
    assert u.api_keys == ["Y" * 40]
    assert u.teams == ["test"]
    assert repr(u) == "<User test@test.com>"


def test_query_user_multiple(mock_server, api):
    mock_server.set_context("num_search_users", 2)
    u = api.user("test@test.com")
    assert u.email == "test@test.com"
    users = api.users("test")
    assert len(users) == 2


def test_delete_api_key(mock_server, api):
    u = api.user("test@test.com")
    assert u.delete_api_key("Y" * 40)
    mock_server.set_context("graphql_conflict", True)
    assert not u.delete_api_key("Y" * 40)


def test_generate_api_key(mock_server, api):
    u = api.user("test@test.com")
    key = u.api_keys[0]
    assert u.generate_api_key()
    assert u.api_keys[-1] != key
    mock_server.set_context("graphql_conflict", True)
    assert u.generate_api_key() is None


def test_nested_summary(api, mock_server):
    run = api.runs("test/test")[0]
    summary_dict = {"a": {"b": {"c": 0.9}}}
    summary = Summary(run, summary_dict)
    assert summary["a"]["b"]["c"] == 0.9
