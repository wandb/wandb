from wandb.cli import cli


def test_launch_bad_api_key(runner, monkeypatch):
    args = [
        "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "--entity",
        "mock_server_entity",
        "--queue",
    ]
    monkeypatch.setenv("WANDB_API_KEY", "4" * 40)
    monkeypatch.setattr("wandb.sdk.internal.internal_api.Api.viewer", lambda a: False)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.launch, args)

        assert "Could not connect with current API-key." in result.output
