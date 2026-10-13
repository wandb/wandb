from __future__ import annotations

import dataclasses
import functools
import inspect
import os
from collections.abc import Mapping
from typing import Any

from .identity import LaunchIdentity, launch_identity

_auto_run: Any = None
_user_run: Any = None
_creating = False
_original_init: Any = None
_project_mismatch_reported = False


@dataclasses.dataclass(frozen=True)
class SharedRunSpec:
    id: str
    label: str
    primary: bool
    identity: LaunchIdentity


def shared_run_spec(env: Mapping[str, str]) -> SharedRunSpec | None:
    identity = launch_identity(env)
    if identity is None:
        return None
    return SharedRunSpec(
        identity.run_id, f"rank{identity.rank}", identity.rank == 0, identity
    )


def ensure_shared_run() -> Any:
    global _auto_run, _creating
    if _auto_run is not None or _creating:
        return _auto_run
    from . import bootstrap

    if not bootstrap.rank_ready or bootstrap.state not in (
        bootstrap.BootstrapState.ARMED,
        bootstrap.BootstrapState.ACTIVE,
    ):
        return None
    import wandb

    try:
        from wandb.sdk import wandb_setup

        if wandb.run is not None:
            bootstrap.attach_run(wandb.run)
            return None
        spec = shared_run_spec(os.environ)
        mode = wandb_setup.singleton().settings.mode
        if mode == "disabled":
            return None
        if spec is None:
            wandb.termwarn(
                "Training telemetry is armed but this rank has no launcher run ID,"
                " so no shared run was created.",
                repeat=False,
            )
            return None
        _creating = True
        _auto_run = (_original_init or wandb.init)(
            id=spec.id,
            project=os.environ.get("WANDB_PROJECT"),
            entity=os.environ.get("WANDB_ENTITY"),
            mode="shared" if mode in ("online", "run", "shared") else mode,
            settings=wandb.Settings(
                x_label=spec.label,
                x_primary=spec.primary,
                # Any later non-terminal request reopens a finished run.
                x_update_finish_state=True,
                x_provenance_level=bootstrap.level,
                # Bounds the per-rank init wait unless the user set one.
                **({} if "WANDB_INIT_TIMEOUT" in os.environ else {"init_timeout": 5}),
            ),
        )
        bootstrap.attach_run(_auto_run)
    except Exception as error:
        bootstrap.state = bootstrap.BootstrapState.UNSUPPORTED
        wandb.termwarn(
            f"Training telemetry could not create the shared run: {type(error).__name__}",
            repeat=False,
        )
    finally:
        _creating = False
    return _auto_run


def install_wandb_init_interceptor() -> None:
    global _original_init
    if _original_init is not None:
        return
    import wandb

    from . import bootstrap

    original = wandb.init
    signature = inspect.signature(original)
    _original_init = original

    @functools.wraps(original)
    def intercepted(*args, **kwargs):
        global _user_run, _project_mismatch_reported
        auto = _auto_run
        if (
            auto is None
            or getattr(auto, "_is_finished", False)
            or bootstrap.state != bootstrap.BootstrapState.ACTIVE
            or (_user_run is not None and not getattr(_user_run, "_is_finished", True))
        ):
            return original(*args, **kwargs)
        bound = signature.bind_partial(*args, **kwargs)
        user_id = bound.arguments.get("id")
        user_project = bound.arguments.get("project")
        same_project = user_project is None or user_project == auto.project
        if user_id == auto.id and not same_project and not _project_mismatch_reported:
            _project_mismatch_reported = True
            wandb.termwarn(
                f"wandb.init(id={user_id!r}, project={user_project!r}) returns the"
                f" shared run in project {auto.project!r}; that run ID is in use."
            )
            if bootstrap.emitter is not None:
                bootstrap.emitter.emit(
                    "capability",
                    {
                        "collector": "writer",
                        "status": "partial",
                        "reason": "run_conflict/project_mismatch",
                    },
                )
        if user_id == auto.id or (user_id is None and same_project):
            if bound.arguments.get("config") is not None:
                auto.config.update(bound.arguments["config"], allow_val_change=True)
            return auto
        if bootstrap.emitter is not None:
            bootstrap.emitter.emit(
                "capability",
                {"collector": "writer", "status": "partial", "reason": "run_conflict"},
            )
        # The shared writer keeps running; the user's run becomes wandb.run beside it.
        forced = "reinit" not in bound.arguments
        if forced:
            kwargs = {**kwargs, "reinit": "create_new"}
        user_run = original(*args, **kwargs)
        if forced and user_run is not None and user_run is not auto:
            from wandb.sdk import wandb_init

            wandb_init._set_global_run(user_run)
        _user_run = user_run
        return user_run

    wandb.init = intercepted
