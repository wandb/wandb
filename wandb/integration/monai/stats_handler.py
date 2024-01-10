from typing import Any, Callable, Sequence, Union

import torch
from monai.utils import is_scalar

import wandb
from wandb.util import get_module

DEFAULT_TAG = "Loss"
ignite_engine = get_module("ignite.engine")


class WandbStatsHandler:
    def __init__(
        self,
        iteration_log: Union[
            bool, Callable[[ignite_engine.Engine, int], bool], int
        ] = True,
        epoch_log: Union[bool, Callable[[ignite_engine.Engine, int], bool], int] = True,
        epoch_event_logger: Union[
            Callable[[ignite_engine.Engine, Any], Any], None
        ] = None,
        iteration_event_logger: Union[
            Callable[[ignite_engine.Engine, Any], Any], None
        ] = None,
        output_transform: Callable = lambda x: x[0],
        global_epoch_transform: Callable = lambda x: x,
        state_attributes: Union[Sequence[str], None] = None,
        tag_name: str = DEFAULT_TAG,
    ) -> None:
        """`WandbStatsHandler` defines a set of Ignite Event-handlers for all the logic related to Weights & Biases logging.

        It can be used for any Ignite Engine(trainer, validator and evaluator) and can support both epoch level and iteration
        level. The expected data source is Ignite `engine.state.output` and `engine.state.metrics`.

        Example:
            ```python
            # For training
            train_wandb_stats_handler = WandbStatsHandler(output_transform=lambda x: x)
            train_wandb_stats_handler.attach(trainer)

            # For evaluation
            val_wandb_stats_handler = WandbStatsHandler(
                output_transform=lambda x: None,
                global_epoch_transform=lambda x: trainer.state.epoch,
            )
            val_wandb_stats_handler.attach(evaluator)
            ```

        Arguments:
            iteration_log: (Union[bool, Callable[[ignite_engine.Engine, int], bool], int]) whether to write data to
                Weights & Biases when iteration completed, default to `True`. It can be also a function or int. If it is an int,
                it will be interpreted as the iteration interval at which the `iteration_event_logger` is called. If it is a
                function, it will be interpreted as an event filter. Event filter function accepts as input engine and event
                value (iteration) and should return `True` or `False`.
            epoch_log: (Union[bool, Callable[[ignite_engine.Engine, int], bool], int]) logging per epoch. Default is True.
                If `True`, logging will be executed every epoch. If `False`, logging will be skipped. If an integer, logging will
                be executed every `epoch_log` epochs. If a callable, it should return a boolean indicating whether to log or not
                on each epoch.
            epoch_event_logger: (Union[Callable[[ignite_engine.Engine, Any], Any], None]) a callable that takes in the engine and
                the current epoch number and logs the desired values. If None, the default epoch logger will be used which logs
                the epoch number and all the metrics in `engine.state.metrics` (if any).
            iteration_event_logger: (Union[Callable[[ignite_engine.Engine, Any], Any], None]) a callable that takes in the engine
                and the current iteration number and logs the desired values. If None, the default iteration logger will be used
                which logs the iteration number and the output value in `engine.state.output` (if any).
            output_transform: (Callable) a callable that is used to transform the ignite.engine.state.output into the value to log.
                For example, if `ignite.engine.state.output` is a tuple `(loss, y_pred, y)`, then use
                `output_transform=lambda x: x[0]` to log `loss`, or use `output_transform=lambda x: x[1:]` to log `(y_pred, y)`.
                Default is `lambda x: x[0]` which corresponds to logging `loss`.
            global_epoch_transform: (Callable) a callable that is used to transform the ignite.engine.state.epoch into the value
                to log. This can be used to log the global step number across multiple epochs. Default is `lambda x: x`.
            state_attributes: (Union[Sequence[str], None]) a list of attributes of `ignite.engine.state` that will be logged.
                If None, nothing will be logged. Default is None.
            tag_name: (str) the name of the loss tag to log. Default is "Loss".
        """
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before initializing `WandbStatsHandler()`"
            )
        self.iteration_log = iteration_log
        self.epoch_log = epoch_log
        self.epoch_event_logger = epoch_event_logger
        self.iteration_event_logger = iteration_event_logger
        self.output_transform = output_transform
        self.global_epoch_transform = global_epoch_transform
        self.state_attributes = state_attributes
        self.tag_name = tag_name
        wandb.define_metric("epoch/epoch")
        wandb.define_metric("epoch/*", step_metric="epoch/epoch")
        wandb.define_metric("iteration/iteration")
        wandb.define_metric("iteration/*", step_metric="iteration/iteration")

    def attach(self, engine: ignite_engine.Engine) -> None:
        """Register a set of Ignite Event-Handlers to a specified Ignite engine.

        Arguments:
            engine: (ignite_engine.Engine) Ignite Engine, it can be a trainer, validator or evaluator.
        """
        if self.iteration_log and not engine.has_event_handler(
            self.iteration_completed, ignite_engine.Events.ITERATION_COMPLETED
        ):
            event = ignite_engine.Events.ITERATION_COMPLETED
            if callable(self.iteration_log):
                event = event(event_filter=self.iteration_log)
            elif self.iteration_log > 1:
                event = event(every=self.iteration_log)
            engine.add_event_handler(event, self.iteration_completed)
        if self.epoch_log and not engine.has_event_handler(
            self.epoch_completed, ignite_engine.Events.EPOCH_COMPLETED
        ):
            event = ignite_engine.Events.EPOCH_COMPLETED
            if callable(self.epoch_log):
                event = event(event_filter=self.epoch_log)
            elif self.epoch_log > 1:
                event = event(every=self.epoch_log)
            engine.add_event_handler(event, self.epoch_completed)

    def epoch_completed(self, engine: ignite_engine.Engine) -> None:
        """Handler for train or validation/evaluation epoch completed Event. Log epoch level events, default values are from Ignite `engine.state.metrics` dict.

        Arguments:
            engine: (ignite_engine.Engine) Ignite Engine, it can be a trainer, validator or evaluator.
        """
        if self.epoch_event_logger is not None:
            self.epoch_event_logger(engine)
        else:
            self.default_epoch_logger(engine)

    def iteration_completed(self, engine: ignite_engine.Engine) -> None:
        """Handler for train or validation/evaluation iteration completed Event. Log iteration level events to Weights & Biases, default values are from Ignite `engine.state.output`.

        Arguments:
            engine: (ignite_engine.Engine) Ignite Engine, it can be a trainer, validator or evaluator.
        """
        if self.iteration_event_logger is not None:
            self.iteration_event_logger(engine)
        else:
            self.default_iteration_logger(engine)

    def default_epoch_logger(self, engine: ignite_engine.Engine) -> None:
        """Execute epoch level event wandb-logging operation.

        Default to write the values from Ignite `engine.state.metrics` dict and log the values of specified attributes of `engine.state`.

        Arguments:
            engine: (ignite_engine.Engine) Ignite Engine, it can be a trainer, validator or evaluator.
        """
        current_epoch = self.global_epoch_transform(engine.state.epoch)
        wandb_loggable_dict = {"epoch/epoch": current_epoch}

        summary_dict = engine.state.metrics
        for name, value in summary_dict.items():
            if is_scalar(value):
                wandb_loggable_dict[f"epoch/{name}"] = value

        if self.state_attributes is not None:
            for attr in self.state_attributes:
                wandb_loggable_dict[f"epoch/{attr}"] = getattr(engine.state, attr, None)

        wandb.log(wandb_loggable_dict)

    def default_iteration_logger(self, engine: ignite_engine.Engine) -> None:
        """Execute iteration level event wandb-logging operation based on Ignite `engine.state.output` data.

        This operation also extracts the values from `self.output_transform(engine.state.output)`,
        since `engine.state.output` is a decollated list and we replicated the loss value for every item
        of the decollated list, the default behavior is to track the loss from `output[0]`.

        Arguments:
            engine: (ignite_engine.Engine) Ignite Engine, it can be a trainer, validator or evaluator.
        """
        loss = self.output_transform(engine.state.output)
        current_iteration = engine.state.iteration
        if loss is None:
            return  # do nothing if output is empty
        wandb_loggable_dict = {"iteration/iteration": current_iteration}
        if isinstance(loss, dict):
            for key, value in loss.items():
                if not is_scalar(value):
                    wandb.termwarn(
                        "ignoring non-scalar output in WandbStatsHandler,"
                        " make sure `output_transform(engine.state.output)` returns"
                        " a scalar or dictionary of key and scalar pairs to avoid this warning."
                        f" {key}:{type(value)}",
                        repeat=False,
                    )
                    continue
                wandb_loggable_dict[f"iteration/{key}"] = (
                    value.item() if isinstance(value, torch.Tensor) else value
                )
        elif is_scalar(loss):
            wandb_loggable_dict[f"iteration/{self.tag_name}"] = (
                loss.item() if isinstance(loss, torch.Tensor) else loss
            )
        else:
            wandb.termwarn(
                "ignoring non-scalar output in WandbStatsHandler,"
                " make sure `output_transform(engine.state.output)` returns"
                " a scalar or a dictionary of key and scalar pairs to avoid this warning."
                f" {type(loss)}",
                repeat=False,
            )

        wandb.log(wandb_loggable_dict)
