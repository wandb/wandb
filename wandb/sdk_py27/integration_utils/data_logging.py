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


# TODO: Generalize the datalogger to build a dataset
# TODO: factor out ability to pass a tables to a labels list (this is an odd overload)


class ValidationDataLogger(object):
    # validation_inputs: Union[Sequence, Dict[str, Sequence]]
    # validation_targets: Optional[Union[Sequence, Dict[str, Sequence]]]
    # validation_indexes: List["_TableIndex"]
    # prediction_row_processor: Optional[Callable]
    # class_labels_table: Optional["wandb.Table"]
    # infer_missing_processors: bool

    def __init__(
        self,
        inputs,
        targets = None,
        indexes = None,
        validation_row_processor = None,
        prediction_row_processor = None,
        input_col_name = "input",
        target_col_name = "target",
        table_name = "wb_validation_data",
        artifact_type = "validation_dataset",
        class_labels = None,
        infer_missing_processors = True,
    ):
        # class_labels_table: Optional["wandb.Table"]
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
        predictions,
        prediction_col_name = "output",
        val_ndx_col_name = "val_row",
        table_name = "validation_predictions",
        commit = False,
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


def _make_example(data):
    # example: Optional[Union[Dict, Sequence, Any]]

    if isinstance(data, dict):
        example = {}
        for key in data:
            example[key] = data[key][0]
    elif hasattr(data, "__len__"):
        example = data[0]
    else:
        example = None

    return example


def _get_example_shape(example):
    shape = []
    if hasattr(example, "__len__"):
        length = len(example)
        shape = [length]
        if length > 0:
            shape += _get_example_shape(example[0])
    return shape


def _bind(lambda_fn, **closure_kwargs):
    def closure(*args, **kwargs):
        _k = {}
        _k.update(kwargs)
        _k.update(closure_kwargs)
        return lambda_fn(*args, **_k)

    return closure


def _infer_single_example_keyed_processor(
    example,
    class_labels_table = None,
    possible_base_example = None,
):
    shape = _get_example_shape(example)
    processors = {}
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
        # processors["min_class"] = lambda n, d, p: class_labels_table.index_ref(  # type: ignore
        #     np.argmin(d)
        # )
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
            processors["class"] = lambda n, d, p: class_labels_table.index_ref(d[0])  # type: ignore
        # else:
        #     processors["val"] = lambda n, d, p: d[0]
    elif len(shape) == 1 and shape[0] <= 10:
        np = wandb.util.get_module(
            "numpy", required="Infering processors require numpy",
        )
        # This could be anything
        if shape[0] <= 10:
            # if less than 10, fan out the results
            processors["node"] = lambda n, d, p: {i: d[i] for i in range(shape[0])}
        # just report the argmax and argmin
        processors["argmax"] = lambda n, d, p: np.argmax(d)
        processors["argmin"] = lambda n, d, p: np.argmin(d)
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

    return processors


def _infer_validation_row_processor(
    example_input,
    example_target,
    class_labels_table = None,
    input_col_name = "input",
    target_col_name = "target",
):
    single_processors = {}
    if isinstance(example_input, dict):
        for key in example_input:
            key_processors = _infer_single_example_keyed_processor(example_input[key])
            for p_key in key_processors:
                single_processors["{}:{}".format(key, p_key)] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx, row[key], None,
                    ),
                    key_processor=key_processors[p_key],
                    key=key,
                )
    else:
        key = input_col_name
        key_processors = _infer_single_example_keyed_processor(example_input)
        for p_key in key_processors:
            single_processors["{}:{}".format(key, p_key)] = _bind(
                lambda ndx, row, key_processor, key: key_processor(
                    ndx, row[key], None,
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
                single_processors["{}:{}".format(key, p_key)] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx, row[key], None,
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
            single_processors["{}:{}".format(key, p_key)] = _bind(
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
    example_prediction,
    example_input,
    # example_target: Union[Dict, Sequence, Any],
    class_labels_table = None,
    input_col_name = "input",
    output_col_name = "output",
):
    single_processors = {}

    if isinstance(example_prediction, dict):
        for key in example_prediction:
            key_processors = _infer_single_example_keyed_processor(
                example_prediction[key], class_labels_table
            )
            for p_key in key_processors:
                single_processors["{}:{}".format(key, p_key)] = _bind(
                    lambda ndx, row, key_processor, key: key_processor(
                        ndx, row[key], None,
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
            single_processors["{}:{}".format(key, p_key)] = _bind(
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
