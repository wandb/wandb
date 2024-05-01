# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

import wandb

if TYPE_CHECKING:
    from wandb.data_types import _TableIndex

CAN_INFER_IMAGE_AND_VIDEO = sys.version_info.major == 3 and sys.version_info.minor >= 5


class ValidationDataLogger:
    """Logs validation data as a wandb.Table.

    ValidationDataLogger is intended to be used inside of library integrations
    in order to facilitate the process of optionally building a validation dataset
    and logging periodic predictions against such validation data using WandB best
    practices.
    """

    validation_inputs: Union[Sequence, Dict[str, Sequence]]
    validation_targets: Optional[Union[Sequence, Dict[str, Sequence]]]
    validation_indexes: List["_TableIndex"]
    prediction_row_processor: Optional[Callable]
    class_labels_table: Optional["wandb.Table"]
    infer_missing_processors: bool

    def __init__(
        self,
        inputs: Union[Sequence, Dict[str, Sequence]],
        targets: Optional[Union[Sequence, Dict[str, Sequence]]] = None,
        indexes: Optional[List["_TableIndex"]] = None,
        validation_row_processor: Optional[Callable] = None,
        prediction_row_processor: Optional[Callable] = None,
        input_col_name: str = "input",
        target_col_name: str = "target",
        table_name: str = "wb_validation_data",
        artifact_type: str = "validation_dataset",
        class_labels: Optional[List[str]] = None,
        infer_missing_processors: bool = True,
    ) -> None:
        """Initialize a new ValidationDataLogger.

        Args:
            inputs: A list of input vectors or dictionary of lists of input vectors
                (used if the model has multiple named inputs)
            targets: A list of target vectors or dictionary of lists of target vectors
                (used if the model has multiple named targets/putputs). Defaults to `None`.
                `targets` and `indexes` cannot both be `None`.
            indexes: An ordered list of `wandb.data_types._TableIndex` mapping the
                input items to their source table. This is most commonly retrieved by using
                `indexes = my_data_table.get_index()`. Defaults to `None`. `targets`
                and `indexes` cannot both be `None`.
            validation_row_processor: A function to apply to the validation data,
                commonly used to visualize the data. The function will receive an `ndx` (`int`)
                and a `row` (`dict`). If `inputs` is a list, then `row["input"]` will be the input
                data for the row. Else, it will be keyed based on the name of the input slot
                (corresponding to `inputs`). If `targets` is a list, then
                `row["target"]` will be the target data for the row. Else, it will
                be keyed based on `targets`. For example, if your input data is a
                single ndarray, but you wish to visualize the data as an image,
                then you can provide `lambda ndx, row: {"img": wandb.Image(row["input"])}`
                as the processor. If `None`, we will try to guess the appropriate processor.
                Ignored if `log_evaluation` is `False` or `val_keys` are present. Defaults to `None`.
            prediction_row_processor: Same as validation_row_processor, but applied to the
                model's output. `row["output"]` will contain the results of the model output.
                Defaults to `None`.
            input_col_name: The name to use for the input column.
                Defaults to `"input"`.
            target_col_name: The name to use for the target column.
                Defaults to `"target"`.
            table_name: The name to use for the validation table.
                Defaults to `"wb_validation_data"`.
            artifact_type: The artifact type to use for the validation data.
                Defaults to `"validation_dataset"`.
            class_labels: Optional list of labels to use in the inferred
                processors. If the model's `target` or `output` is inferred to be a class,
                we will attempt to map the class to these labels. Defaults to `None`.
            infer_missing_processors: Determines if processors are inferred if
                they are missing. Defaults to True.
        """
        class_labels_table: Optional[wandb.Table]
        if isinstance(class_labels, list) and len(class_labels) > 0:
            class_labels_table = wandb.Table(
                columns=["label"], data=[[label] for label in class_labels]
            )
        else:
            class_labels_table = None

        if indexes is None:
            assert targets is not None
            local_validation_table = wandb.Table(columns=[], data=[])

            if isinstance(targets, dict):
                for col_name in targets:
                    local_validation_table.add_column(col_name, targets[col_name])
            else:
                local_validation_table.add_column(target_col_name, targets)

            if isinstance(inputs, dict):
                for col_name in inputs:
                    local_validation_table.add_column(col_name, inputs[col_name])
            else:
                local_validation_table.add_column(input_col_name, inputs)

            if validation_row_processor is None and infer_missing_processors:
                example_input = _make_example(inputs)
                example_target = _make_example(targets)
                if example_input is not None and example_target is not None:
                    validation_row_processor = _infer_validation_row_processor(
                        example_input,
                        example_target,
                        class_labels_table,
                        input_col_name,
                        target_col_name,
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
        self.input_col_name = input_col_name

    def make_predictions(
        self, predict_fn: Callable
    ) -> Union[Sequence, Dict[str, Sequence]]:
        """Produce predictions by passing `validation_inputs` to `predict_fn`.

        Args:
            predict_fn (Callable): Any function which can accept `validation_inputs` and produce
                a list of vectors or dictionary of lists of vectors

        Returns:
            (Sequence | Dict[str, Sequence]): The returned value of predict_fn
        """
        return predict_fn(self.validation_inputs)

    def log_predictions(
        self,
        predictions: Union[Sequence, Dict[str, Sequence]],
        prediction_col_name: str = "output",
        val_ndx_col_name: str = "val_row",
        table_name: str = "validation_predictions",
        commit: bool = True,
    ) -> wandb.data_types.Table:
        """Log a set of predictions.

        Intended usage:

        vl.log_predictions(vl.make_predictions(self.model.predict))

        Args:
            predictions (Sequence | Dict[str, Sequence]): A list of prediction vectors or dictionary
                of lists of prediction vectors
            prediction_col_name (str, optional): the name of the prediction column. Defaults to "output".
            val_ndx_col_name (str, optional): The name of the column linking prediction table
                to the validation ata table. Defaults to "val_row".
            table_name (str, optional): name of the prediction table. Defaults to "validation_predictions".
            commit (bool, optional): determines if commit should be called on the logged data. Defaults to False.
        """
        pred_table = wandb.Table(columns=[], data=[])
        if isinstance(predictions, dict):
            for col_name in predictions:
                pred_table.add_column(col_name, predictions[col_name])
        else:
            pred_table.add_column(prediction_col_name, predictions)
        pred_table.add_column(val_ndx_col_name, self.validation_indexes)

        if self.prediction_row_processor is None and self.infer_missing_processors:
            example_prediction = _make_example(predictions)
            example_input = _make_example(self.validation_inputs)
            if example_prediction is not None and example_input is not None:
                self.prediction_row_processor = _infer_prediction_row_processor(
                    example_prediction,
                    example_input,
                    self.class_labels_table,
                    self.input_col_name,
                    prediction_col_name,
                )

        if self.prediction_row_processor is not None:
            pred_table.add_computed_columns(self.prediction_row_processor)

        wandb.log({table_name: pred_table}, commit=commit)
        return pred_table


def _make_example(data: Any) -> Optional[Union[Dict, Sequence, Any]]:
    """Used to make an example input, target, or output."""
    example: Optional[Union[Dict, Sequence, Any]]

    if isinstance(data, dict):
        example = {}
        for key in data:
            example[key] = data[key][0]
    elif hasattr(data, "__len__"):
        example = data[0]
    else:
        example = None

    return example


def _get_example_shape(example: Union[Sequence, Any]):
    """Get the shape of an object if applicable."""
    shape = []
    if not isinstance(example, str) and hasattr(example, "__len__"):
        length = len(example)
        shape = [length]
        if length > 0:
            shape += _get_example_shape(example[0])
    return shape


def _bind(lambda_fn: Callable, **closure_kwargs: Any) -> Callable:
    """Create a closure around a lambda function by binding `closure_kwargs` to the function."""

    def closure(*args: Any, **kwargs: Any) -> Any:
        _k = {}
        _k.update(kwargs)
        _k.update(closure_kwargs)
        return lambda_fn(*args, **_k)

    return closure


def _infer_single_example_keyed_processor(
    example: Union[Sequence, Any],
    class_labels_table: Optional["wandb.Table"] = None,
    possible_base_example: Optional[Union[Sequence, Any]] = None,
) -> Dict[str, Callable]:
    """Infers a processor from a single example.

    Infers a processor from a single example with optional class_labels_table
    and base_example. Base example is useful for cases such as segmentation masks
    """
    shape = _get_example_shape(example)
    processors: Dict[str, Callable] = {}
    if (
        class_labels_table is not None
        and len(shape) == 1
        and shape[0] == len(class_labels_table.data)
    ):
        np = wandb.util.get_module(
            "numpy",
            required="Inferring processors require numpy",
        )
        # Assume these are logits
        class_names = class_labels_table.get_column("label")

        processors["max_class"] = lambda n, d, p: class_labels_table.index_ref(  # type: ignore
            np.argmax(d)
        )
        # TODO: Consider adding back if users ask
        # processors["min_class"] = lambda n, d, p: class_labels_table.index_ref(  # type: ignore
        #     np.argmin(d)
        # )

        values = np.unique(example)
        is_one_hot = len(values) == 2 and set(values) == {0, 1}
        if not is_one_hot:
            processors["score"] = lambda n, d, p: {
                class_names[i]: d[i] for i in range(shape[0])
            }
    elif (
        len(shape) == 1
        and shape[0] == 1
        and (
            isinstance(example[0], int)
            or (hasattr(example, "tolist") and isinstance(example.tolist()[0], int))  # type: ignore
        )
    ):
        # assume this is a class
        if class_labels_table is not None:
            processors["class"] = (
                lambda n, d, p: class_labels_table.index_ref(d[0])
                if d[0] < len(class_labels_table.data)
                else d[0]
            )  # type: ignore
        else:
            processors["val"] = lambda n, d, p: d[0]
    elif len(shape) == 1:
        np = wandb.util.get_module(
            "numpy",
            required="Inferring processors require numpy",
        )
        # This could be anything
        if shape[0] <= 10:
            # if less than 10, fan out the results
            # processors["node"] = lambda n, d, p: {i: d[i] for i in range(shape[0])}
            processors["node"] = lambda n, d, p: [
                d[i].tolist() if hasattr(d[i], "tolist") else d[i]
                for i in range(shape[0])
            ]
        # just report the argmax and argmin
        processors["argmax"] = lambda n, d, p: np.argmax(d)

        values = np.unique(example)
        is_one_hot = len(values) == 2 and set(values) == {0, 1}
        if not is_one_hot:
            processors["argmin"] = lambda n, d, p: np.argmin(d)
    elif len(shape) == 2 and CAN_INFER_IMAGE_AND_VIDEO:
        if (
            class_labels_table is not None
            and possible_base_example is not None
            and shape == _get_example_shape(possible_base_example)
        ):
            # consider this a segmentation mask
            processors["image"] = lambda n, d, p: wandb.Image(
                p,
                masks={
                    "masks": {
                        "mask_data": d,
                        "class_labels": class_labels_table.get_column("label"),  # type: ignore
                    }
                },
            )
        else:
            # consider this a 2d image
            processors["image"] = lambda n, d, p: wandb.Image(d)
    elif len(shape) == 3 and CAN_INFER_IMAGE_AND_VIDEO:
        # consider this an image
        processors["image"] = lambda n, d, p: wandb.Image(d)
    elif len(shape) == 4 and CAN_INFER_IMAGE_AND_VIDEO:
        # consider this a video
        processors["video"] = lambda n, d, p: wandb.Video(d)

    return processors


def _infer_validation_row_processor(
    example_input: Union[Dict, Sequence],
    example_target: Union[Dict, Sequence, Any],
    class_labels_table: Optional["wandb.Table"] = None,
    input_col_name: str = "input",
    target_col_name: str = "target",
) -> Callable:
    """Infers the composite processor for the validation data."""
    single_processors = {}
    if isinstance(example_input, dict):
        for key in example_input:
            key_processors = _infer_single_example_keyed_processor(example_input[key])
            for p_key in key_processors:
                single_processors[f"{key}:{p_key}"] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx,
                        row[key],
                        None,
                    ),
                    key_processor=key_processors[p_key],
                    key=key,
                )
    else:
        key = input_col_name
        key_processors = _infer_single_example_keyed_processor(example_input)
        for p_key in key_processors:
            single_processors[f"{key}:{p_key}"] = _bind(
                lambda ndx, row, key_processor, key: key_processor(
                    ndx,
                    row[key],
                    None,
                ),
                key_processor=key_processors[p_key],
                key=key,
            )

    if isinstance(example_target, dict):
        for key in example_target:
            key_processors = _infer_single_example_keyed_processor(
                example_target[key], class_labels_table
            )
            for p_key in key_processors:
                single_processors[f"{key}:{p_key}"] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx,
                        row[key],
                        None,
                    ),
                    key_processor=key_processors[p_key],
                    key=key,
                )
    else:
        key = target_col_name
        key_processors = _infer_single_example_keyed_processor(
            example_target,
            class_labels_table,
            example_input if not isinstance(example_input, dict) else None,
        )
        for p_key in key_processors:
            single_processors[f"{key}:{p_key}"] = _bind(
                lambda ndx, row, key_processor, key: key_processor(
                    ndx,
                    row[key],
                    row[input_col_name]
                    if not isinstance(example_input, dict)
                    else None,
                ),
                key_processor=key_processors[p_key],
                key=key,
            )

    def processor(ndx, row):
        return {key: single_processors[key](ndx, row) for key in single_processors}

    return processor


def _infer_prediction_row_processor(
    example_prediction: Union[Dict, Sequence],
    example_input: Union[Dict, Sequence],
    class_labels_table: Optional["wandb.Table"] = None,
    input_col_name: str = "input",
    output_col_name: str = "output",
) -> Callable:
    """Infers the composite processor for the prediction output data."""
    single_processors = {}

    if isinstance(example_prediction, dict):
        for key in example_prediction:
            key_processors = _infer_single_example_keyed_processor(
                example_prediction[key], class_labels_table
            )
            for p_key in key_processors:
                single_processors[f"{key}:{p_key}"] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx,
                        row[key],
                        None,
                    ),
                    key_processor=key_processors[p_key],
                    key=key,
                )
    else:
        key = output_col_name
        key_processors = _infer_single_example_keyed_processor(
            example_prediction,
            class_labels_table,
            example_input if not isinstance(example_input, dict) else None,
        )
        for p_key in key_processors:
            single_processors[f"{key}:{p_key}"] = _bind(
                lambda ndx, row, key_processor, key: key_processor(
                    ndx,
                    row[key],
                    ndx.get_row().get("val_row").get_row().get(input_col_name)
                    if not isinstance(example_input, dict)
                    else None,
                ),
                key_processor=key_processors[p_key],
                key=key,
            )

    def processor(ndx, row):
        return {key: single_processors[key](ndx, row) for key in single_processors}

    return processor
