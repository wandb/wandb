"""Implementation for WANDB_MODE=disabled."""

import time
from typing import cast

from typing_extensions import Self, override

import wandb
from wandb.sdk import wandb_config, wandb_metric, wandb_run, wandb_settings
from wandb.sdk.artifacts import artifact
from wandb.sdk.lib import module
from wandb.sdk.lib.disabled import SummaryDisabled


def init_noop_run(
    settings: wandb_settings.Settings,
    config: dict[str, object],
) -> wandb_run.Run:
    """Create a mode=disabled run and set it as the global run."""
    noop_run = NoopRun(settings, config)

    module.set_global(
        run=noop_run,
        config=noop_run.config,
        log=noop_run.log,
        summary=noop_run.summary,
        save=noop_run.save,
        use_artifact=noop_run.use_artifact,
        log_artifact=noop_run.log_artifact,
        define_metric=noop_run.define_metric,
        alert=noop_run.alert,
        watch=noop_run.watch,
        unwatch=noop_run.unwatch,
    )

    return noop_run


class _Noop:
    """A callable object for which every attribute is self."""

    def __getattr__(self, _: str) -> Self:
        return self

    def __call__(self, *args, **kwargs) -> Self:
        return self


class NoopRun(wandb_run.Run):
    """A subclass of Run that generally does nothing.

    This is a very bad implementation because any new method on Run is
    automatically inherited here, so there's always a chance of NoopRun
    accidentally doing something. A better way is possible, but requires
    some restructuring: we can make `wandb.Run` an ABC subclassed by both
    `NoopRun` and the real implementation.
    """

    def __init__(
        self,
        settings: wandb_settings.Settings,
        config: dict[str, object],
    ) -> None:
        super().__init__(settings=settings)

        self._config = wandb_config.Config()
        self._config.update(config)

        self.summary = SummaryDisabled()  # type: ignore

        self._start_time = time.time()
        self._starting_step = 0
        self._step = 0
        self._attach_id = None
        self._interface = None

    # Replace all of these symbols with functions that return None.
    for __symbol in (
        "alert",
        "finish_artifact",
        "get_project_url",
        "get_sweep_url",
        "get_url",
        "link_artifact",
        "link_model",
        "use_artifact",
        "log_code",
        "log_model",
        "use_model",
        "mark_preempting",
        "restore",
        "status",
        "watch",
        "write_logs",
        "unwatch",
        "upsert_artifact",
        "_finish",
    ):
        locals()[__symbol] = lambda *args, **kwargs: None

    @override
    def log(self, data, *args, **kwargs) -> None:
        self.summary.update(data)

    @override
    def finish(self, *args, **kwargs) -> None:
        if wandb.run is self:
            module.unset_globals()

    @override
    def define_metric(self, *args, **kwargs) -> wandb_metric.Metric:
        return wandb_metric.Metric("dummy")

    @override
    def save(self, *args, **kwargs) -> bool:
        return False

    @property
    @override
    def step(self) -> int:
        return 0

    @property
    @override
    def url(self) -> None:
        return None

    @property
    @override
    def project_url(self) -> None:
        return None

    @property
    @override
    def sweep_url(self) -> None:
        return None

    @override
    def log_artifact(self, *args, **kwargs) -> artifact.Artifact:
        # Cast to object first to tell the type-checker this is intentional.
        noop = cast(object, _Noop())
        return cast(artifact.Artifact, noop)
