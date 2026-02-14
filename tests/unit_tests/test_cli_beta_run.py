"""Unit tests for ``wandb beta run`` and ``wandb beta eval`` CLI commands."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from click.testing import CliRunner
from wandb.cli.beta import beta
from wandb.cli.beta_run import (
    BASE_JOB,
    EVAL_JOB,
    SANDBOX_WORKDIR,
    SandboxConfigError,
    _parse_env,
    _parse_mounts,
    _parse_resources,
    _parse_secrets,
    _split_mount_spec,
    _validate_sandbox_path,
    script_sandbox_path,
    submit_sandbox_job,
    upload_files_artifact,
)


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def script(tmp_path):
    """Create a real script file and return its path."""
    p = tmp_path / "train.py"
    p.write_text("# train")
    return p


class TestParseEnv:
    def test_basic_key_val(self):
        assert _parse_env(["FOO=bar"]) == {"FOO": "bar"}

    def test_value_containing_equals(self):
        result = _parse_env(["DSN=postgres://host?opt=1"])
        assert result["DSN"] == "postgres://host?opt=1"

    def test_missing_equals_raises(self):
        with pytest.raises(SandboxConfigError, match="KEY=VAL"):
            _parse_env(["INVALID"])

    def test_empty_inputs(self):
        assert _parse_env() == {}
        assert _parse_env(None) == {}


class TestParseSecrets:
    def test_remap(self):
        assert _parse_secrets(["MY_VAR:MY_SECRET"]) == {"MY_VAR": "MY_SECRET"}

    def test_no_remap(self):
        assert _parse_secrets(["MY_SECRET"]) == {"MY_SECRET": "MY_SECRET"}

    def test_split_on_first_colon(self):
        assert _parse_secrets(["VAR:a:b"]) == {"VAR": "a:b"}

    @pytest.mark.parametrize("spec", ["", ":MY_SECRET", "MY_VAR:"])
    def test_invalid_spec_raises(self, spec):
        with pytest.raises(SandboxConfigError):
            _parse_secrets([spec])


class TestParseResources:
    def test_valid_json_object(self):
        assert _parse_resources('{"gpu": 1}') == {"gpu": 1}

    def test_none_returns_none(self):
        assert _parse_resources(None) is None

    def test_invalid_json_raises(self):
        with pytest.raises(SandboxConfigError, match="Invalid JSON"):
            _parse_resources("not json")

    def test_json_array_raises(self):
        with pytest.raises(SandboxConfigError, match="object"):
            _parse_resources("[1, 2]")

    def test_json_scalar_raises(self):
        with pytest.raises(SandboxConfigError, match="object"):
            _parse_resources("42")


class TestSplitMountSpec:
    def test_no_colon_defaults_to_sandbox_workdir(self):
        assert _split_mount_spec("/home/user/f.py") == (
            "/home/user/f.py",
            f"{SANDBOX_WORKDIR}/f.py",
        )

    def test_relative_no_colon_defaults_to_sandbox_workdir(self):
        assert _split_mount_spec("data.csv") == (
            "data.csv",
            f"{SANDBOX_WORKDIR}/data.csv",
        )

    def test_with_sandbox_path(self):
        assert _split_mount_spec("train.py:/app/train.py") == (
            "train.py",
            "/app/train.py",
        )

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="os.path.splitdrive only splits drive letters on Windows",
    )
    def test_windows_drive_letter_not_split(self):
        assert _split_mount_spec("C:\\data\\f.py:/sandbox/f.py") == (
            "C:\\data\\f.py",
            "/sandbox/f.py",
        )


class TestValidateSandboxPath:
    @pytest.mark.parametrize(
        "path", ["/app/train.py", "/etc/config.json", "/data/sub/file.py"]
    )
    def test_valid_absolute_paths_pass(self, path):
        _validate_sandbox_path(path)  # should not raise

    @pytest.mark.parametrize("path", ["train.py", "sub/dir/file.py", "relative.py"])
    def test_relative_paths_rejected(self, path):
        with pytest.raises(SandboxConfigError, match="must be absolute"):
            _validate_sandbox_path(path)

    @pytest.mark.parametrize("path", ["/", "/app/", "/data/sub/"])
    def test_directory_paths_rejected(self, path):
        with pytest.raises(SandboxConfigError, match="must point to a file"):
            _validate_sandbox_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/app/../etc/passwd",
        ],
    )
    def test_traversal_rejected(self, path):
        with pytest.raises(SandboxConfigError, match="must not contain"):
            _validate_sandbox_path(path)


class TestParseMounts:
    def test_script_mounted_at_sandbox_workdir(self, script):
        mounts, script_sandbox = _parse_mounts(str(script))
        assert script_sandbox == f"{SANDBOX_WORKDIR}/train.py"
        assert mounts[str(script)] == script_sandbox

    def test_additional_mount_included(self, tmp_path, script):
        config = tmp_path / "config.json"
        config.write_text("{}")
        mounts, _ = _parse_mounts(str(script), [f"{config}:/etc/config.json"])
        assert mounts[str(config)] == "/etc/config.json"
        assert str(script) in mounts

    def test_missing_script_raises(self):
        with pytest.raises(SandboxConfigError, match="Script not found"):
            _parse_mounts("/nonexistent/script.py")

    def test_missing_mount_file_raises(self, script):
        with pytest.raises(SandboxConfigError, match="Mount file not found"):
            _parse_mounts(str(script), ["/nonexistent/data.csv:/data/data.csv"])

    def test_relative_sandbox_path_raises(self, tmp_path, script):
        data = tmp_path / "data.csv"
        data.write_text("x")
        with pytest.raises(SandboxConfigError, match="must be absolute"):
            _parse_mounts(str(script), [f"{data}:relative.csv"])

    def test_traversal_in_sandbox_path_raises(self, tmp_path, script):
        data = tmp_path / "data.csv"
        data.write_text("x")
        with pytest.raises(SandboxConfigError, match="must not contain"):
            _parse_mounts(str(script), [f"{data}:/app/../escape.csv"])

    def test_remounting_script_raises(self, script):
        with pytest.raises(SandboxConfigError, match="already mounted"):
            _parse_mounts(str(script), [f"{script}:/custom/path.py"])

    def test_duplicate_local_file_raises(self, tmp_path, script):
        f = tmp_path / "data.csv"
        f.write_text("x")
        with pytest.raises(SandboxConfigError, match="already mounted"):
            _parse_mounts(str(script), [f"{f}:/a.csv", f"{f}:/b.csv"])

    def test_duplicate_sandbox_path_raises(self, tmp_path, script):
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("a")
        b.write_text("b")
        with pytest.raises(SandboxConfigError, match="Duplicate sandbox path"):
            _parse_mounts(
                str(script),
                [f"{a}:/data/file.csv", f"{b}:/data/file.csv"],
            )

    def test_symlink_resolved(self, tmp_path, script):
        """Symlinks are resolved so the real path is uploaded."""
        real_file = tmp_path / "real.csv"
        real_file.write_text("data")
        link = tmp_path / "link.csv"
        link.symlink_to(real_file)
        mounts, _ = _parse_mounts(str(script), [f"{link}:/data/file.csv"])
        assert str(real_file.resolve()) in mounts


class TestScriptSandboxPath:
    def test_returns_sandbox_workdir_with_basename(self):
        assert (
            script_sandbox_path("/home/user/train.py") == f"{SANDBOX_WORKDIR}/train.py"
        )

    def test_relative_path(self):
        assert script_sandbox_path("train.py") == f"{SANDBOX_WORKDIR}/train.py"


class TestSubmitSandboxJob:
    def _dry_run(self, **kwargs):
        config = submit_sandbox_job(dry_run=True, **kwargs)
        return config["overrides"]["run_config"]

    def test_all_options(self):
        rc = self._dry_run(
            command="python",
            args=["train.py", "--lr", "0.01"],
            image="pytorch:latest",
            env=["FOO=bar"],
            secrets={"model_api_key": "MY_KEY"},
            resources='{"gpu": 1}',
            timeout=3600,
            project="myproj",
            entity="my-team",
            entity_name="my-team",
            queue="q",
        )
        assert rc == {
            "command": "python",
            "args": ["train.py", "--lr", "0.01"],
            "image": "pytorch:latest",
            "env_vars": {
                "FOO": "bar",
                "WANDB_PROJECT": "myproj",
                "WANDB_ENTITY": "my-team",
                "WANDB_ENTITY_NAME": "my-team",
            },
            "resources": {"gpu": 1},
            "timeout": 3600,
            "model_api_key": "secret://MY_KEY",
        }

    def test_defaults(self):
        rc = self._dry_run(queue="q")
        assert rc == {
            "image": "python:3.11",
            "env_vars": {},
        }

    def test_project_entity_auto_injected(self):
        rc = self._dry_run(project="proj", entity="team", entity_name="team", queue="q")
        assert rc["env_vars"] == {
            "WANDB_PROJECT": "proj",
            "WANDB_ENTITY": "team",
            "WANDB_ENTITY_NAME": "team",
        }

    def test_user_env_not_overwritten(self):
        rc = self._dry_run(
            env=["WANDB_PROJECT=user-proj"],
            project="cli-proj",
            queue="q",
        )
        assert rc["env_vars"] == {
            "WANDB_PROJECT": "user-proj",
        }

    def test_secret_collides_with_config_key_raises(self):
        with pytest.raises(SandboxConfigError, match="collides"):
            submit_sandbox_job(
                secrets={"image": "MY_SECRET"},
                queue="q",
                dry_run=True,
            )

    def test_args_without_command_raises(self):
        with pytest.raises(SandboxConfigError, match="args without a command"):
            submit_sandbox_job(
                args=["train.py", "--lr", "0.01"],
                image="pytorch:latest",
                queue="q",
                dry_run=True,
            )


class TestBetaRun:
    """Test ``wandb beta run`` CLI wiring."""

    def _run(self, cli_runner, args):
        result = cli_runner.invoke(
            beta, ["run", *args, "--entity-name", "en", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        rc = json.loads(result.output)["overrides"]["run_config"]
        # files_artifact contains dynamic temp paths; verify it exists
        # then strip it so callers can assert against a stable dict.
        assert "files_artifact" in rc
        rc.pop("files_artifact")
        return rc

    def test_script_and_args_wired(self, script, cli_runner):
        rc = self._run(cli_runner, [str(script), "arg1", "-q", "q"])
        assert rc == {
            "command": "python",
            "args": [f"{SANDBOX_WORKDIR}/train.py", "arg1"],
            "image": "python:3.11",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
        }

    def test_unknown_options_forwarded_as_script_args(self, script, cli_runner):
        rc = self._run(
            cli_runner,
            [str(script), "--foo", "bar", "-lr", "0.01", "-q", "q"],
        )
        assert rc == {
            "command": "python",
            "args": [f"{SANDBOX_WORKDIR}/train.py", "--foo", "bar", "-lr", "0.01"],
            "image": "python:3.11",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
        }

    def test_secrets_wired(self, script, cli_runner):
        rc = self._run(
            cli_runner,
            [str(script), "-q", "q", "-s", "VAR1:SEC1", "--secret", "VAR2:SEC2"],
        )
        assert rc == {
            "command": "python",
            "args": [f"{SANDBOX_WORKDIR}/train.py"],
            "image": "python:3.11",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
            "VAR1": "secret://SEC1",
            "VAR2": "secret://SEC2",
        }

    def test_missing_script_errors(self, cli_runner):
        result = cli_runner.invoke(
            beta, ["run", "-q", "q", "--entity-name", "en", "--dry-run"]
        )
        assert result.exit_code != 0

    def test_relative_script_path_resolved_to_sandbox(self, tmp_path, cli_runner):
        """Args should use the sandbox path even when invoked with a relative path."""
        script = tmp_path / "train.py"
        script.write_text("# train")
        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            rc = self._run(cli_runner, ["train.py", "-q", "q"])
        finally:
            os.chdir(old_cwd)
        assert rc["args"][0] == f"{SANDBOX_WORKDIR}/train.py"

    @mock.patch("wandb.sdk.launch.launch_add")
    @mock.patch("wandb.cli.beta_run.upload_files_artifact", return_value="e/p/art:v0")
    @mock.patch("wandb.cli.beta._require_auth")
    def test_run_uses_base_job(
        self, _mock_auth, _mock_upload, mock_launch_add, script, cli_runner
    ):
        """``wandb beta run`` submits with BASE_JOB (the default)."""
        mock_launch_add.return_value = mock.MagicMock()
        result = cli_runner.invoke(
            beta, ["run", str(script), "-q", "q", "--entity-name", "en"]
        )
        assert result.exit_code == 0, result.output
        mock_launch_add.assert_called_once()
        assert mock_launch_add.call_args.kwargs["job"] == BASE_JOB


class TestBetaEval:
    """Test ``wandb beta eval`` CLI wiring."""

    def _run(self, cli_runner, args):
        result = cli_runner.invoke(
            beta, ["eval", *args, "--entity-name", "en", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["overrides"]["run_config"]

    def test_task_and_model_wired(self, cli_runner):
        rc = self._run(cli_runner, ["swebench", "-m", "openai/gpt-4", "-q", "q"])
        assert rc == {
            "command": "python3",
            "args": ["evals.py", "swebench", "--model", "openai/gpt-4"],
            "image": "exianwb/inspect_ai_evals:latest",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
        }

    def test_eval_options_wired(self, cli_runner):
        rc = self._run(
            cli_runner,
            [
                "swebench",
                "-m",
                "openai/gpt-4",
                "--model-base-url",
                "http://localhost:8080",
                "--limit",
                "10",
                "--create-leaderboard",
                "-q",
                "q",
            ],
        )
        assert rc == {
            "command": "python3",
            "args": [
                "evals.py",
                "swebench",
                "--model",
                "openai/gpt-4",
                "--model-base-url",
                "http://localhost:8080",
                "--limit",
                "10",
                "--create-leaderboard",
            ],
            "image": "exianwb/inspect_ai_evals:latest",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
        }

    def test_eval_secrets_wired(self, cli_runner):
        rc = self._run(
            cli_runner,
            [
                "swebench",
                "-m",
                "openai/gpt-4",
                "-q",
                "q",
                "--model-secret",
                "OPENAI_API_KEY",
                "--hf-secret",
                "HF_TOKEN",
                "--scorer-secret",
                "SCORER_KEY",
            ],
        )
        assert rc == {
            "command": "python3",
            "args": ["evals.py", "swebench", "--model", "openai/gpt-4"],
            "image": "exianwb/inspect_ai_evals:latest",
            "env_vars": {"WANDB_ENTITY_NAME": "en"},
            "model_api_key": "secret://OPENAI_API_KEY",
            "hf_token": "secret://HF_TOKEN",
            "scorer_api_key": "secret://SCORER_KEY",
        }

    @mock.patch("wandb.sdk.launch.launch_add")
    @mock.patch("wandb.cli.beta._require_auth")
    def test_eval_uses_eval_job(self, _mock_auth, mock_launch_add, cli_runner):
        """``wandb beta eval`` submits with EVAL_JOB."""
        mock_launch_add.return_value = mock.MagicMock()
        result = cli_runner.invoke(
            beta,
            [
                "eval",
                "swebench",
                "-m",
                "openai/gpt-4",
                "-q",
                "q",
                "--entity-name",
                "en",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_launch_add.assert_called_once()
        assert mock_launch_add.call_args.kwargs["job"] == EVAL_JOB


class TestUploadFilesArtifact:
    @mock.patch("wandb.cli.beta_run.wandb.Settings")
    @mock.patch("wandb.cli.beta_run.wandb.init")
    @mock.patch("wandb.cli.beta_run.wandb.Artifact")
    def test_entry_names_have_leading_slash_stripped(
        self, mock_artifact_cls, mock_init, mock_settings
    ):
        """Entry names are relative (leading / stripped) so artifact.download() works.

        The executor reconstructs absolute mount paths by prepending /.
        """
        artifact = mock.MagicMock()
        artifact.name = "sandbox-files-abc12345:v0"
        mock_artifact_cls.return_value = artifact

        mock_run = mock.MagicMock()
        mock_run.entity = "my-team"
        mock_run.project = "proj"
        mock_init.return_value.__enter__ = mock.Mock(return_value=mock_run)
        mock_init.return_value.__exit__ = mock.Mock(return_value=False)

        result = upload_files_artifact(
            {
                "/home/user/src/train.py": "/app/train.py",
                "/home/user/data/config.json": "/etc/config.json",
            },
            project="proj",
            entity="my-team",
        )

        assert result == "my-team/proj/sandbox-files-abc12345:v0"
        # Leading / stripped from entry names
        artifact.add_file.assert_any_call(
            "/home/user/src/train.py", name="app/train.py"
        )
        artifact.add_file.assert_any_call(
            "/home/user/data/config.json", name="etc/config.json"
        )
        assert artifact.add_file.call_count == 2
