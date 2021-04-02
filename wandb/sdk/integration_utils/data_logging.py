# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.
import wandb

if wandb.TYPE_CHECKING:

    from typing import TYPE_CHECKING, Callable, Dict, Union, Optional, List, Any
    from collections.abc import Sequence

    if TYPE_CHECKING:
        from wandb.data_types import _TableIndex


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
        class_labels: Optional[Union[List[str], "wandb.Table"]] = None,
        infer_missing_processors: bool = True,
    ):
        class_labels_table: Optional["wandb.Table"]
        if isinstance(class_labels, list) and len(class_labels) > 0:
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

    def make_predictions(self, predict_fn):
        return predict_fn(self.validation_inputs)

    def log_predictions(
        self,
        predictions: Union[Sequence, Dict[str, Sequence]],
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
            example_input = _make_example(self.validation_inputs)
            # example_target = _make_example(self.validation_targets)
            if (
                example_prediction is not None
                # and example_target is not None
                and example_input is not None
            ):
                self.prediction_row_processor = _infer_prediction_row_processor(
                    example_prediction,
                    example_input,
                    # example_target,
                    self.class_labels_table,
                    self.input_col_name,
                    prediction_col_name,
                )

        if self.prediction_row_processor is not None:
            pred_table.add_computed_columns(self.prediction_row_processor)

        wandb.log({table_name: pred_table})


def _make_example(data: Any) -> Optional[Union[Dict, Sequence, Any]]:
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
    shape = []
    if hasattr(example, "__len__"):
        length = len(example)
        shape = [length]
        if length > 0:
            shape += _get_example_shape(example[0])
    return shape


def _infer_single_example_keyed_processor(
    example: Union[Sequence, Any],
    class_labels_table: Optional["wandb.Table"] = None,
    possible_base_example: Optional[Union[Sequence, Any]] = None,
) -> Dict[str, Callable]:
    shape = _get_example_shape(example)
    processors: Dict[str, Callable] = {}
    if (
        class_labels_table is not None
        and len(shape) == 1
        and shape[0] == len(class_labels_table.data)
    ):
        np = wandb.util.get_module(
            "numpy", required="Infering processors require numpy",
        )
        # Assume these are logits
        class_names = class_labels_table.get_column("label")
        processors["max_class"] = lambda n, d, p: class_labels_table.index_ref(  # type: ignore
            np.argmax(d)
        )
        processors["min_class"] = lambda n, d, p: class_labels_table.index_ref(  # type: ignore
            np.argmin(d)
        )
        processors["scores"] = lambda n, d, p: {
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
            processors["class"] = lambda n, d, p: class_labels_table.index_ref(d[0])  # type: ignore
        else:
            processors["class"] = lambda n, d, p: d[0]
    elif len(shape) == 1 and shape[0] <= 10:
        np = wandb.util.get_module(
            "numpy", required="Infering processors require numpy",
        )
        # This could be anything
        if shape[0] <= 10:
            # if less than 10, fan out the results
            processors["n"] = lambda n, d, p: {i: d[i] for i in range(shape[0])}
        # just report the argmax and argmin
        processors["argmax"] = lambda n, d, p: np.argmax(d)
        processors["argmin"] = lambda n, d, p: np.argmin(d)
    # elif len(shape) == 1 and shape[0] > 10:
    #     # consider this Audio? - probably just pass for now
    #     pass
    elif len(shape) == 2:
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
    elif len(shape) == 3:
        # consider this an image
        processors["image"] = lambda n, d, p: wandb.Image(d)
    elif len(shape) == 4:
        if shape[-1] in (1, 3, 4):
            # consider this an image
            processors["image"] = lambda n, d, p: wandb.Image(d)
        else:
            # consider this a video
            processors["image"] = lambda n, d, p: wandb.Video(d)
    else:
        # no idea
        pass

    # def processor(ndx, data, possible_base_data):
    #     return {processors[key](ndx, data, possible_base_data) for key in processors}

    return processors


def _make_closure(key_processors, p_key, key, use_base=False, base_data_resolver=None):
    return lambda ndx, row: key_processors[p_key](
        ndx,
        row[key],
        base_data_resolver(ndx, row) if use_base and base_data_resolver else None,
    )


def _infer_validation_row_processor(
    example_input: Union[Dict, Sequence],
    example_target: Union[Dict, Sequence, Any],
    class_labels_table: Optional["wandb.Table"] = None,
    input_col_name: str = "input",
    target_col_name: str = "target",
) -> Callable:
    single_processors = {}
    if isinstance(example_input, dict):
        for key in example_input:
            key_processors = _infer_single_example_keyed_processor(example_input[key])
            for p_key in key_processors:
                single_processors["{}_{}".format(key, p_key)] = _make_closure(
                    key_processors, p_key, key
                )
    else:
        key = input_col_name
        key_processors = _infer_single_example_keyed_processor(example_input)
        for p_key in key_processors:
            single_processors["{}_{}".format(key, p_key)] = _make_closure(
                key_processors, p_key, key
            )

    if isinstance(example_target, dict):
        for key in example_target:
            key_processors = _infer_single_example_keyed_processor(
                example_target[key], class_labels_table
            )
            for p_key in key_processors:
                single_processors["{}_{}".format(key, p_key)] = _make_closure(
                    key_processors, p_key, key
                )
    else:
        key = target_col_name
        key_processors = _infer_single_example_keyed_processor(
            example_target,
            class_labels_table,
            example_input if not isinstance(example_input, dict) else None,
        )
        for p_key in key_processors:
            single_processors["{}_{}".format(key, p_key)] = _make_closure(
                key_processors,
                p_key,
                key,
                not isinstance(example_input, dict),
                lambda ndx, row: row[input_col_name],
            )

    def processor(ndx, row):
        return {key: single_processors[key](ndx, row) for key in single_processors}

    # new_col_fns = {}
    # if isinstance(example_input, dict):
    #     for key in example_input:
    #         processor_dict = _infer_validation_input_processor_dict(example_input[key])

    # def processor(ndx, row):
    #     return {
    #         col:new_col_fns[col](ndx, row) for col in new_col_fns
    #     }

    return processor


def _infer_prediction_row_processor(
    example_prediction: Union[Dict, Sequence],
    example_input: Union[Dict, Sequence],
    # example_target: Union[Dict, Sequence, Any],
    class_labels_table: Optional["wandb.Table"] = None,
    input_col_name: str = "input",
    output_col_name: str = "output",
) -> Callable:
    single_processors = {}

    if isinstance(example_prediction, dict):
        for key in example_prediction:
            key_processors = _infer_single_example_keyed_processor(
                example_prediction[key], class_labels_table
            )
            for p_key in key_processors:
                single_processors["{}_{}".format(key, p_key)] = _make_closure(
                    key_processors, p_key, key
                )
    else:
        key = output_col_name
        key_processors = _infer_single_example_keyed_processor(
            example_prediction,
            class_labels_table,
            example_input if not isinstance(example_input, dict) else None,
        )
        for p_key in key_processors:
            single_processors["{}_{}".format(key, p_key)] = _make_closure(
                key_processors,
                p_key,
                key,
                not isinstance(example_input, dict),
                lambda ndx, row: ndx.get_row()
                .get("val_ndx")
                .get_row()
                .get(input_col_name),
            )

    def processor(ndx, row):
        return {key: single_processors[key](ndx, row) for key in single_processors}

    # return None
    # def processor(ndx, row):
    #     return {
    #         col:new_col_fns[col](ndx, row) for col in new_col_fns
    #     }

    return processor
