# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.
import wandb

if wandb.TYPE_CHECKING:

    from typing import TYPE_CHECKING, Callable, Dict, Union, Optional, List
    from collections.abc import Iterator

    if TYPE_CHECKING:
        from wandb.data_types import _TableIndex


class ValidationDataLogger(object):
    def __init__(
        self,
        inputs: Union[Iterator, Dict[str, Iterator]],
        targets: Optional[Union[Iterator, Dict[str, Iterator]]] = None,
        indexes: Optional[List["_TableIndex"]] = None,
        validation_row_processor: Optional[Callable] = None,
        prediction_row_processor: Optional[Callable] = None,
        input_col_name: str = "input",
        target_col_name: str = "target",
        table_name: str = "wb_validation_data",
        artifact_type: str = "validation_dataset",
    ):
        if indexes is None:
            assert targets is not None
            local_validation_table = wandb.Table(columns=[], data=[])
            if isinstance(inputs, dict):
                for col_name in inputs:
                    local_validation_table.add_column(col_name, inputs[col_name])
            else:
                local_validation_table.add_column(input_col_name, inputs)

            if isinstance(targets, dict):
                for col_name in targets:
                    local_validation_table.add_column(col_name, targets[col_name])
            else:
                local_validation_table.add_column(target_col_name, targets)

            if validation_row_processor is not None:
                local_validation_table.add_computed_columns(validation_row_processor)

            self._local_validation_artifact = wandb.Artifact(table_name, artifact_type)
            self._local_validation_artifact.add(
                local_validation_table, "validation_data"
            )
            if wandb.run:
                wandb.run.use_artifact(self._local_validation_artifact)
            indexes = local_validation_table.get_index()
        else:
            self._local_validation_artifact = None

        self.validation_inputs = inputs
        self.validation_indexes = indexes
        self.prediction_row_processor = prediction_row_processor

    def make_predictions(self, predict_fn):
        return predict_fn(self.validation_inputs)

    def log_predictions(
        self,
        predictions: Union[Iterator, Dict[str, Iterator]],
        prediction_col_name: str = "output",
        val_ndx_col_name: str = "val_ndx",
        table_name: str = "validation_predictions",
        commit: bool = False,
    ):
        if self._local_validation_artifact is not None:
            self._local_validation_artifact.wait()

        pred_table = wandb.Table(columns=[], data=[])
        pred_table.add_column(val_ndx_col_name, self.validation_indexes)
        if isinstance(predictions, dict):
            for col_name in predictions:
                pred_table.add_column(col_name, predictions[col_name])
        else:
            pred_table.add_column(prediction_col_name, predictions)

        if self.prediction_row_processor is not None:
            pred_table.add_computed_columns(self.prediction_row_processor)

        wandb.log({table_name: pred_table})
