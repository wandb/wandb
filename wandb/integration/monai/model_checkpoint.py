from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

from ignite.engine import Engine

import wandb
from wandb.util import get_module

ignite_engine = get_module("ignite.engine")
ignite_handlers = get_module("ignite.handlers")


class WandbModelCheckpoint(ignite_handlers.ModelCheckpoint):
    """`WandbModelCheckpoint` handler can be used to periodically log model checkpoints to Weights & Biases as a [model artifact](https://docs.wandb.ai/guides/artifacts).

    Example:
        ```python
        checkpoint_handler = WandbModelCheckpoint(
            "./runs_dict/", "net", n_saved=10, require_empty=False
        )
        trainer.add_event_handler(
            event_name=Events.EPOCH_COMPLETED,
            handler=checkpoint_handler,
            to_save={"net": net, "opt": opt},
        )
        ```

    Arguments:
        dirname: (Union[str, Path]) Directory path where objects will be saved.
        filename_prefix: (str) Prefix for the file names to which objects will be saved.
        score_function: (Optional[Callable]) if not None, it should be a function taking a single argument, an
            `ignite.engine.engine.Engine` object, and return a score (`float`). Objects with highest scores
            will be retained.
        score_name: (Optional[str]) if `score_function` not None, it is possible to store its value using `score_name`.
        n_saved: (Union[int, None]) Number of objects that should be kept on disk. Older files will be removed. If set to
            `None`, all objects are kept.
        atomic: (bool) If True, objects are serialized to a temporary file, and then moved to final destination, so that
            files are guaranteed to not be damaged (for example if exception occurs during saving).
        require_empty: (bool) If True, will raise exception if there are any files starting with `filename_prefix` in the
            directory `dirname`.
        create_dir: (bool) If True, will create directory `dirname` if it does not exist.
        global_step_transform: (Optional[Callable]) global step transform function to output a desired global step.
            Input of the function is `(engine, event_name)`. Output of function should be an integer.
            Default is None, global_step based on attached engine. If provided, uses function output as global_step.
            To setup global step from another engine, please use :meth:`~ignite.handlers.global_step_from_engine`.
        archived: (bool) Deprecated argument as models saved by `torch.save` are already compressed.
        filename_pattern: (Optional[str]) If `filename_pattern` is provided, this pattern will be used to render
            checkpoint filenames. If the pattern is not defined, the default pattern would be used.
        include_self: (bool) Whether to include the `state_dict` of this object in the checkpoint. If `True`, then
            there must not be another object in `to_save` with key `checkpointer`.
        greater_or_equal: (bool) if `True`, the latest equally scored model is stored. Otherwise, the first model.
            Default, `False`.
        save_on_rank: (int) Which rank to save the objects on, in the distributed configuration. Used to
            instantiate a :class:`ignite.handlers.DiskSaver` and is also passed to the parent class.
        kwargs: (Any) Accepted keyword arguments for `torch.save` or `xm.save` in `DiskSaver`.
    """

    def __init__(
        self,
        dirname: Union[str, Path],
        filename_prefix: str = "",
        score_function: Optional[Callable] = None,
        score_name: Optional[str] = None,
        n_saved: Optional[int] = 1,
        atomic: bool = True,
        require_empty: bool = True,
        create_dir: bool = True,
        global_step_transform: Optional[Callable] = None,
        archived: bool = False,
        filename_pattern: Optional[str] = None,
        include_self: bool = False,
        greater_or_equal: bool = False,
        save_on_rank: int = 0,
        **kwargs: Any,
    ):
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before initializing `WandbModelCheckpoint()`"
            )
        super().__init__(
            dirname,
            filename_prefix,
            None,
            score_function,
            score_name,
            n_saved,
            atomic,
            require_empty,
            create_dir,
            True,
            global_step_transform,
            archived,
            filename_pattern,
            include_self,
            greater_or_equal,
            save_on_rank,
            **kwargs,
        )

    def __call__(self, engine: Engine, to_save: Mapping):
        super().__call__(engine, to_save)
        artifact = wandb.Artifact(name=f"run-{wandb.run.id}-checkpoint", type="model")
        artifact.add_file(local_path=self.last_checkpoint)
        wandb.log_artifact(
            artifact,
            aliases=[f"iteration-{engine.state.iteration}|epoch-{engine.state.epoch}"],
        )
