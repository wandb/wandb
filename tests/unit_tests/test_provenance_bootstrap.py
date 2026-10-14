import os
import subprocess
import sys
import zipfile

import pytest


def test_built_wheel_contains_exactly_one_root_startup_hook():
    from wandb.sdk.provenance import startup

    wheel = os.environ.get("WANDB_PROVENANCE_TEST_WHEEL")
    if wheel is None:
        pytest.skip("set WANDB_PROVENANCE_TEST_WHEEL to the built wheel")
    with zipfile.ZipFile(wheel) as archive:
        assert archive.namelist().count(startup.PTH_NAME) == 1
        assert archive.read(startup.PTH_NAME).decode() == startup.PTH_LINE


def _site_dir(tmp_path):
    from wandb.sdk.provenance import startup

    (tmp_path / startup.PTH_NAME).write_text(startup.PTH_LINE)
    return str(tmp_path)


def _clean_env(tmp_path, **values):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WANDB_")}
    env.update(WANDB_DIR=str(tmp_path), WANDB_MODE="offline", **values)
    return env


@pytest.mark.parametrize("level", [None, "", "true", "2"])
def test_pth_does_not_import_wandb_unless_level_is_valid(tmp_path, level):
    env = _clean_env(tmp_path)
    if level is not None:
        env["WANDB_X_PROVENANCE_LEVEL"] = level
    code = (
        f"import site,sys;site.addsitedir({_site_dir(tmp_path)!r});"
        "print('wandb' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


_RANK_ENV = {
    "WANDB_X_PROVENANCE_LEVEL": "0",
    "WANDB_RUN_ID": "job-c1",
    "RANK": "0",
    "LOCAL_RANK": "0",
    "GROUP_RANK": "0",
    "WORLD_SIZE": "1",
}


def _run_rank_process(tmp_path, body):
    code = (
        f"import site;site.addsitedir({_site_dir(tmp_path)!r})\n"
        "import wandb, torch.distributed as dist\n"
        "from wandb.sdk.provenance import bootstrap\n" + body
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=_clean_env(tmp_path, **_RANK_ENV),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_process_without_process_group_creates_no_run(tmp_path):
    result = _run_rank_process(
        tmp_path,
        "assert wandb.run is None\n"
        "assert bootstrap.state == bootstrap.BootstrapState.ARMED, bootstrap.state\n",
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob("wandb-telemetry"))


def test_failed_process_group_init_still_records_the_attempt(tmp_path):
    import gzip
    import json

    code = (
        f"import site;site.addsitedir({_site_dir(tmp_path)!r})\n"
        "import wandb, torch.distributed as dist\n"
        "try:\n"
        "    dist.init_process_group('no-such-backend', rank=0, world_size=1)\n"
        "except Exception:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('init should fail')\n"
        "assert wandb.run is not None\n"
        "wandb.run.finish(exit_code=1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=_clean_env(
            tmp_path,
            **_RANK_ENV,
            TORCHELASTIC_RESTART_COUNT="1",
            TORCHELASTIC_MAX_RESTARTS="3",
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    (manifest_path,) = tmp_path.rglob("wandb-telemetry/v2/manifest/*.json")
    manifest = json.loads(manifest_path.read_text())
    assert (manifest["attempt"], manifest["exit"]) == (
        1,
        {"code": 1, "reason": "attempt_failed"},
    )
    records = [
        json.loads(line)
        for chunk in tmp_path.rglob("wandb-telemetry/v2/chunks/*/*.jsonl.gz")
        for line in gzip.decompress(chunk.read_bytes()).splitlines()
    ]
    (lifecycle,) = [r for r in records if r["kind"] == "lifecycle"]
    assert (lifecycle["attempt"], lifecycle["reason"], lifecycle["max_restarts"]) == (
        1,
        "attempt_failed",
        3,
    )


_INIT_PG = (
    "dist.init_process_group('gloo', init_method={store!r}, rank=0, world_size=1)\n"
    "auto = wandb.run\n"
    "assert auto is not None and auto.id == 'job-c1'\n"
    "assert auto.settings.x_label == 'rank0' and auto.settings.mode == 'offline'\n"
    "assert bootstrap.state == bootstrap.BootstrapState.ACTIVE, bootstrap.state\n"
)


def test_process_group_creates_writer_and_compatible_init_returns_it(tmp_path):
    store = (tmp_path / "store").as_uri()
    result = _run_rank_process(
        tmp_path,
        _INIT_PG.format(store=store)
        + "assert auto.settings.x_update_finish_state is True\n"
        "assert (auto.settings.finish_timeout, auto.settings.silent) == (0.0, False)\n"
        "assert wandb.init(id='job-c1', config={'a': 1}) is auto\n"
        "assert auto.config.a == 1\n"
        "emitter, wrapped = bootstrap.emitter, dist.init_process_group\n"
        "auto.finish()\n"
        "assert bootstrap.state == bootstrap.BootstrapState.DISABLED\n"
        "assert not emitter._thread.is_alive()\n"
        "assert dist.init_process_group is wrapped.__wrapped__\n",
    )
    assert result.returncode == 0, result.stderr


def test_conflicting_init_keeps_writer_and_makes_user_run_global(tmp_path):
    import json

    store = (tmp_path / "store").as_uri()
    result = _run_rank_process(
        tmp_path,
        _INIT_PG.format(store=store)
        + "user = wandb.init(id='user-run', project='user-project')\n"
        "assert user is not auto and not auto._is_finished\n"
        "assert wandb.run is user\n"
        "assert (user.id, user.project) == ('user-run', 'user-project')\n"
        "assert bootstrap.state == bootstrap.BootstrapState.ACTIVE\n"
        "assert wandb.init(id='user-run', project='user-project') is user\n"
        "user.finish()\n"
        "assert not auto._is_finished\n"
        "assert bootstrap.state == bootstrap.BootstrapState.ACTIVE\n"
        "auto.finish()\n",
    )
    assert result.returncode == 0, result.stderr
    (manifest,) = tmp_path.rglob("wandb-telemetry/v2/manifest/*.json")
    capability = json.loads(manifest.read_text())["capabilities"]["writer"]
    assert capability == {"status": "partial", "reason": "run_conflict"}


def test_same_id_in_other_project_returns_writer_with_one_warning(tmp_path):
    import json

    store = (tmp_path / "store").as_uri()
    result = _run_rank_process(
        tmp_path,
        _INIT_PG.format(store=store) + "assert auto.project != 'torchtitan'\n"
        "assert wandb.init(id='job-c1', project='torchtitan', config={'b': 2}) is auto\n"
        "assert wandb.init(id='job-c1', project='torchtitan') is auto\n"
        "assert wandb.run is auto and auto.config.b == 2\n"
        "assert bootstrap.state == bootstrap.BootstrapState.ACTIVE\n"
        "auto.finish()\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("that run ID is in use") == 1
    (manifest,) = tmp_path.rglob("wandb-telemetry/v2/manifest/*.json")
    capability = json.loads(manifest.read_text())["capabilities"]["writer"]
    assert capability == {
        "status": "partial",
        "reason": "run_conflict/project_mismatch",
    }


def test_every_rank_reports_its_own_finish_state(monkeypatch):
    import wandb
    from wandb.sdk.provenance import bootstrap, run

    calls = []
    monkeypatch.setattr(run, "_original_init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(run, "_auto_run", None)
    monkeypatch.setattr(bootstrap, "rank_ready", True)
    monkeypatch.setattr(bootstrap, "level", 0)
    monkeypatch.setattr(bootstrap, "state", bootstrap.BootstrapState.ARMED)
    monkeypatch.setattr(bootstrap, "attach_run", lambda _: None)
    monkeypatch.setattr(wandb, "run", None)
    monkeypatch.delenv("WANDB_INIT_TIMEOUT", raising=False)
    for rank in ("1", "0"):
        for key, value in {**_RANK_ENV, "RANK": rank, "WORLD_SIZE": "2"}.items():
            monkeypatch.setenv(key, value)
        run.ensure_shared_run()
    monkeypatch.setenv("WANDB_INIT_TIMEOUT", "30")
    run.ensure_shared_run()
    assert [call["settings"].x_update_finish_state for call in calls] == [
        True,
        True,
        True,
    ]
    assert [call["settings"].init_timeout for call in calls] == [5.0, 5.0, 90.0]
    for call in calls:
        settings = call["settings"]
        assert (settings.finish_timeout, settings.silent) == (0.0, False)


def test_missing_identity_or_failed_create_warns_once_locally(monkeypatch):
    import wandb
    from wandb.sdk.provenance import bootstrap, run

    warnings = []
    monkeypatch.setattr(
        wandb, "termwarn", lambda message, **_: warnings.append(message)
    )
    monkeypatch.setattr(run, "_auto_run", None)
    monkeypatch.setattr(bootstrap, "rank_ready", True)
    monkeypatch.setattr(bootstrap, "state", bootstrap.BootstrapState.ARMED)
    monkeypatch.setattr(wandb, "run", None)
    for key in ("RANK", "WANDB_RUN_ID", "TORCHELASTIC_RUN_ID", "K8S_JOB_UID"):
        monkeypatch.delenv(key, raising=False)
    run.ensure_shared_run()
    assert len(warnings) == 1 and "no launcher run ID" in warnings[0]

    def failing_init(**kwargs):
        raise TimeoutError

    monkeypatch.setattr(run, "_original_init", failing_init)
    for key, value in _RANK_ENV.items():
        monkeypatch.setenv(key, value)
    run.ensure_shared_run()
    assert bootstrap.state == bootstrap.BootstrapState.UNSUPPORTED
    assert "TimeoutError" in warnings[-1]


def test_attach_uses_run_level_and_defers_until_rank_ready(monkeypatch):
    from types import SimpleNamespace

    from wandb.sdk.provenance import bootstrap

    requests = []

    class Interface:
        def deliver_provenance_start(self, request):
            requests.append(request)
            return SimpleNamespace(
                wait_or=lambda timeout: SimpleNamespace(
                    accepted=False, protocol_version=2, writer_id=""
                )
            )

    run = SimpleNamespace(
        id="job",
        _settings=SimpleNamespace(x_provenance_level=1),
        _interface=Interface(),
        _teardown_hooks=[],
    )
    for key, value in {**_RANK_ENV, "WANDB_RUN_ID": "job"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(bootstrap, "level", 0)
    monkeypatch.setattr(bootstrap, "state", bootstrap.BootstrapState.ARMED)
    monkeypatch.setattr(bootstrap, "_installed", True)
    monkeypatch.setattr(bootstrap, "_attached", None)
    monkeypatch.setattr(bootstrap, "_hook_seen", True)
    monkeypatch.setattr(bootstrap, "rank_ready", False)
    bootstrap.attach_run(run)
    assert requests == []
    monkeypatch.setattr(bootstrap, "rank_ready", True)
    bootstrap.attach_run(run)
    assert [request.level for request in requests] == [1]


def test_finder_delegates_to_other_meta_path_finders(monkeypatch):
    import importlib.machinery

    from wandb.sdk.provenance import bootstrap

    loader = importlib.machinery.SourceFileLoader("torchtitan", __file__)

    class Custom:
        def find_spec(self, fullname, path=None, target=None):
            return importlib.machinery.ModuleSpec(fullname, loader)

    finder = bootstrap._Finder()
    monkeypatch.setattr(sys, "meta_path", [finder, Custom()])
    spec = finder.find_spec("torchtitan")
    assert isinstance(spec.loader, bootstrap._Loader)
    assert spec.loader.original is loader


@pytest.mark.parametrize("level", [None, 0, 1])
def test_run_log_does_not_trigger_collection(monkeypatch, mock_run, level):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    cuda, distributed = MagicMock(), MagicMock()
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=cuda, distributed=distributed)
    )
    run = mock_run(use_magic_mock=True, settings={"x_provenance_level": level})
    run.log({"a": 1})
    cuda.is_initialized.assert_not_called()
    distributed.is_initialized.assert_not_called()
    run._interface.publish_provenance_record.assert_not_called()


@pytest.mark.parametrize("rank", [0, 3])
def test_shared_run_spec_is_stable(rank):
    from wandb.sdk.provenance.run import shared_run_spec

    spec = shared_run_spec(
        {
            "RANK": str(rank),
            "LOCAL_RANK": str(rank),
            "GROUP_RANK": "0",
            "WORLD_SIZE": "8",
            "WANDB_RUN_ID": "job-7",
        }
    )
    assert spec.id == "job-7"
    assert spec.label == f"rank{rank}"
    assert spec.primary is (rank == 0)


def test_default_rendezvous_id_falls_back_to_the_job_uid():
    from wandb.sdk.provenance.identity import launch_identity

    env = {**_RANK_ENV, "TORCHELASTIC_RUN_ID": "none", "K8S_JOB_UID": "uid-1"}
    del env["WANDB_RUN_ID"]
    assert launch_identity(env).run_id == "uid-1"
    assert launch_identity({**env, "K8S_JOB_UID": ""}) is None


def test_missing_stable_identity_creates_no_run():
    from wandb.sdk.provenance.run import shared_run_spec

    assert shared_run_spec({"RANK": "1", "WORLD_SIZE": "8"}) is None


def test_site_disabled_reports_missing_hook():
    from wandb.sdk.provenance import bootstrap

    assert bootstrap.status() == "startup_hook_missing"


def test_level1_configured_before_torch_import(monkeypatch):
    from wandb.sdk.provenance.level1 import install_level1_bootstrap

    monkeypatch.delenv("TORCH_NCCL_TRACE_BUFFER_SIZE", raising=False)
    monkeypatch.delenv("TORCH_FR_BUFFER_SIZE", raising=False)
    present = "torch" in sys.modules
    install_level1_bootstrap()
    assert ("torch" in sys.modules) is present
    assert os.environ["TORCH_FR_BUFFER_SIZE"] == "2000"
    assert "TORCH_NCCL_TRACE_BUFFER_SIZE" not in os.environ
