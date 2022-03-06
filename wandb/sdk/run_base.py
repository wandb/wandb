from enum import Enum
import os
from typing import Any, Callable, List, Dict, Optional, Union

from wandb import Settings


class Policy(Enum):
    LIVE = "live"
    NOW = "now"
    END = "end"


class RunBase:
    def __init__(self) -> None:
        self._attach_id = None
        self._init_pid = os.getpid()
        self._settings = Settings()

    def __setattr__(self, attr: str, value: object) -> None:
        if getattr(self, "_frozen", None) and not hasattr(self, attr):
            raise Exception(f"Attribute {attr} is not supported on Run object.")
        super().__setattr__(attr, value)

    def __getstate__(self) -> Dict[str, Any]:
        """Custom pickler."""
        # We only pickle in service mode
        if not self._settings or not self._settings._require_service:
            return

        _attach_id = self._attach_id
        if not _attach_id:
            return

        return dict(
            _attach_id=_attach_id,
            _init_pid=self._init_pid,
            _is_attaching=self._is_attaching,
        )

    def __setstate__(self, state: Any) -> None:
        """Custom unpickler."""
        if not state:
            return

        _attach_id = state.get("_attach_id")
        if not _attach_id:
            return

        # TODO this solution will not work when we pass `_attach_id` to `wandb._attach`
        self.__dict__["_settings"] = Settings()
        self.__dict__["_settings"].update(state.pop("_settings", {}))

        self.__dict__.update(state)
        if self._init_pid == os.getpid():
            raise RuntimeError("attach in the same process is not supported")

    def __enter__(self) -> "RunBase":
        return self

    def __exit__(
        self,
        # exc_type: Type[BaseException],
        # exc_val: BaseException,
        # exc_tb: TracebackType,
    ) -> bool:
        ...

    def _freeze(self) -> None:
        self._frozen = True

    def _on_setup(self) -> None:
        ...

    def _on_init(self) -> None:
        ...

    def _on_start(self) -> None:
        ...

    def _on_attach(self) -> None:
        ...

    def _on_finish(self) -> None:
        ...

    def _on_final(self) -> None:
        ...

    def define_metric(
        self,
        name: str,
        # step_metric: Union[str, wandb_metric.Metric, None] = None,
        step_sync: bool = None,
        hidden: bool = None,
        summary: str = None,
        goal: str = None,
        overwrite: bool = None,
        **kwargs: Any,
        # ) -> wandb_metric.Metric:
    ):
        ...

    def log(
        self,
        data: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
        sync: Optional[bool] = None,
    ) -> None:
        pass

    def log_code(
        root: str = os.getcwd(),
        name: Optional[str] = None,
        include_fn: Callable[[str], bool] = lambda path: path.endswith(".py"),
        # exclude_fn: Callable[[str], bool] = filenames.exclude_wandb_fn,
        # ) -> Optional[Artifact]:
    ) -> None:
        pass

    # @_attach
    def log_artifact(
        self,
        # artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        # ) -> wandb_artifacts.Artifact:
    ):
        ...

    def use_artifact(
        self,
        # artifact_or_name: Union[str, public.Artifact, Artifact],
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        use_as: Optional[str] = None,
        # ) -> Union[public.Artifact, Artifact]:
    ):
        ...

    def upsert_artifact(
        self,
        # artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
        # ) -> wandb_artifacts.Artifact:
    ):
        ...

    def finish_artifact(
        self,
        # artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
        # ) -> wandb_artifacts.Artifact:
    ):
        ...

    def watch(
        self,
        models,
        criterion=None,
        log="gradients",
        log_freq=100,
        idx=None,
        log_graph=False,
    ) -> None:
        # wandb.watch(models, criterion, log, log_freq, idx, log_graph)
        ...

    def unwatch(self, models=None) -> None:  # type: ignore
        ...
        # wandb.unwatch(models=models)

    def save(
        self,
        glob_str: Optional[str] = None,
        base_path: Optional[str] = None,
        policy: str = "live",
    ) -> Union[bool, List[str]]:
        pass

    def restore(
        self,
        name: str,
        run_path: Optional[str] = None,
        replace: bool = False,
        root: Optional[str] = None,
        # ) -> Union[None, TextIO]:
    ):
        pass

    def alert(
        self,
        title: str,
        text: str,
        # level: Union[str, "AlertLevel"] = None,
        # wait_duration: Union[int, float, timedelta, None] = None,
    ) -> None:
        ...

    #  @_attach
    def mark_preempting(self) -> None:
        ...

    def finish(self, exit_code: int = None) -> None:
        pass

    def join(self, exit_code: int = None) -> None:
        pass


if __name__ == "__main__":
    ...
