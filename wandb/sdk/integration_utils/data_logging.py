# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.
import wandb

if wandb.TYPE_CHECKING:

    from typing import TYPE_CHECKING, Callable, Dict, Union, Optional, List, Any
    from collections.abc import Iterator

    if TYPE_CHECKING:
        from wandb.data_types import _TableIndex


# TODO: Add support for class labels + tables
# TODO: Add automated inference types
#  - model output len(shape) == 1
#    - argmin, argmax
#    - if shape[0] == class length, also do a lookup for both and logits
#  - model input:
#     - 1d audio?
#     - 2d: image
#     - 3d image
#     - 4d video (mp4)
#  - support for named inoputs and outpouts
# targets - classification (class labels defined)
#          - binary
#         - regression


class ValidationDataLogger(object):
    validation_inputs: Union[Iterator, Dict[str, Iterator]]
    validation_targets: Optional[Union[Iterator, Dict[str, Iterator]]]
    validation_indexes: List["_TableIndex"]
    prediction_row_processor: Optional[Callable]
    class_labels_table: Optional["wandb.Table"]
    infer_missing_processors: bool

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
        class_labels: Optional[Union[List[str], "wandb.Table"]] = None,
        infer_missing_processors: bool = True,
    ):
        class_labels_table: Optional["wandb.Table"]
        if isinstance(class_labels, list):
            class_labels_table = wandb.Table(
                columns=["label"], data=[[label] for label in class_labels]
            )
        elif isinstance(class_labels, wandb.Table):
            class_labels_table = class_labels
        else:
            class_labels_table = None

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

            if validation_row_processor is None and infer_missing_processors:
                example_input = _make_example(inputs)
                example_target = _make_example(targets)
                if example_input is not None and example_target is not None:
                    validation_row_processor = _infer_validation_row_processor(
                        example_input, example_target, class_labels_table
                    )

            if validation_row_processor is not None:
                local_validation_table.add_computed_columns(validation_row_processor)

            local_validation_artifact = wandb.Artifact(table_name, artifact_type)
            local_validation_artifact.add(local_validation_table, "validation_data")
            if wandb.run:
                wandb.run.use_artifact(local_validation_artifact)
            indexes = local_validation_table.get_index()
        else:
            local_validation_artifact = None

        self.class_labels_table = class_labels_table
        self.validation_inputs = inputs
        self.validation_targets = targets
        self.validation_indexes = indexes
        self.prediction_row_processor = prediction_row_processor
        self.infer_missing_processors = infer_missing_processors
        self.local_validation_artifact = local_validation_artifact

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
        if self.local_validation_artifact is not None:
            self.local_validation_artifact.wait()

        pred_table = wandb.Table(columns=[], data=[])
        pred_table.add_column(val_ndx_col_name, self.validation_indexes)
        if isinstance(predictions, dict):
            for col_name in predictions:
                pred_table.add_column(col_name, predictions[col_name])
        else:
            pred_table.add_column(prediction_col_name, predictions)

        if self.prediction_row_processor is None and self.infer_missing_processors:
            example_prediction = _make_example(predictions)
            example_target = _make_example(self.validation_targets)
            if example_prediction is not None and example_target is not None:
                self.prediction_row_processor = _infer_prediction_row_processor(
                    example_prediction, example_target, self.class_labels_table
                )

        if self.prediction_row_processor is not None:
            pred_table.add_computed_columns(self.prediction_row_processor)

        wandb.log({table_name: pred_table})


def _make_example(data: Any) -> Optional[Union[Dict, Iterator, Any]]:
    example: Optional[Union[Dict, Iterator, Any]]

    if isinstance(data, dict):
        example = {}
        for key in data:
            example[key] = data[key][0]
    elif hasattr(data, "__len__"):
        example = data[0]
    else:
        example = None

    return example


def _infer_validation_row_processor(
    example_input: Union[Dict, Iterator],
    example_target: Union[Dict, Iterator, Any],
    class_labels_table: Optional["wandb.Table"] = None,
):
    return None


def _infer_prediction_row_processor(
    example_prediction: Union[Dict, Iterator],
    example_target: Union[Dict, Iterator, Any],
    class_labels_table: Optional["wandb.Table"] = None,
):
    return None
