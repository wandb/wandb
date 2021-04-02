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
            example_input = _make_example(self.validation_inputs)
            example_target = _make_example(self.validation_targets)
            if (
                example_prediction is not None
                and example_target is not None
                and example_input is not None
            ):
                self.prediction_row_processor = _infer_prediction_row_processor(
                    example_prediction,
                    example_input,
                    example_target,
                    self.class_labels_table,
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


'''
Processor Inference Overview
----------------------------

In this section, I will describe the logic flow to infer processor function
from data. Basically, we are dealing with the following dataflow:

Input -----> Model ------> Output----->Activation------\/
                                                    Evaluator---->Score
Target--------------------------------------------------^

In our function, we have access to the input, target, and output as well as an optional class table provided
for classification tasks

There are two important layers to understand:
1. Multi- vs Single- style Inputs/Targets/Outputs
2. Shape/Type based Inference

First, Inputs/Targets/Outputs can either be multi or single version. In the multi-version
they are keyed dictionaries. In the single version, they are most likely ndarrays, except for edge
cases when the target is just a single value.

So, to start with we have the following possibilities:

    Input   Target  Output      Inference Strategies:   Input   Target  Output
    --------------------------------------------------------------------------
    Single  Single  Single  |                           i       it      ito   
    Single  Single  Multi   |            n              i       it      o
    Single  Multi   Single  |            n              i       it(b)   o 
    Single  Multi   Multi   |                           i       it(b)   ito(m)
    Multi   Single  Single  |                           i       t       to
    Multi   Single  Multi   |            n              i       t       to(b)
    Multi   Multi   Single  |            n              i       it(m)   to(b)
    Multi   Multi   Multi   |                           i       it(m)   ito(m)

Ok, then after you select the correct inference strategy, we do something like the following:

    strat   has class   shape
    --------------------------  
    i       y           (x)
                        (x,y)
                        (x,y,z)
                        (x,y,z,t)
            n
    t       y
            n
    it      y
            n
    o       y
            n
    to      y
            n
    io?     y
            n
    ito     y
            n
    

'''

def _get_example_shape(example: Union[Iterator, Any]):
    shape = []
    if hasattr(example, "__len__"):
        length = len(example)
        shape = [length]
        if length > 0:
            shape += _get_example_shape(example[0])
    return shape

def _infer_single_example_processor(example: Union[Iterator, Any], class_labels_table: Optional["wandb.Table"] = None, possible_base_example:Optional[Union[Iterator, Any]]=None):
    shape = _get_example_shape(example)
    if class_labels_table is not None and len(shape) == 1 and shape[0] == len(class_labels_table.data):
        # Assume these are logits
        # do argmax, argmin, and logit scores
        pass
    elif class_labels_table is not None and len(shape) == 1 and shape[0] == 1 and isinstance(example[0], int):
        # assume this is a class
        # just map to the class table
        pass
    elif len(shape) == 1 and shape[0] <= 10:
        # fan out the results (we don't quite know what this is)
        pass
    elif len(shape) == 1 and shape[0] > 10:
        # consider this Audio
        pass
    elif len(shape) == 2:
        if class_labels_table is not None and possible_base_example is not None and shape == _get_example_shape(possible_base_example):
            # consider this a segmentation mask
            pass
        else:
            # consider this a 2d image
            pass
    elif len(shape) == 3:
        # consider this an image
    elif len(shape) == 4:
        # consider this a video
    else:
        # no idea
        pass

    def processor(data):
        return {}

    return processor


def _infer_validation_row_processor(
    example_input: Union[Dict, Iterator],
    example_target: Union[Dict, Iterator, Any],
    class_labels_table: Optional["wandb.Table"] = None,
):
    return None
    # single_processors = {}
    # if isinstance(example_input, dict):
    #     for key in example_input:
    #         key_processor = _infer_single_input_processor(example_input[key])
    #         for p_key in key_processor:
    #             single_processors["{}_{}".format(key, p_key)] = lambda ndx, row: key_processor[p_key](row[key])
    # else:
    #     key = "input"
    #     key_processor = _infer_single_input_processor(example_input)
    #     for p_key in key_processor:
    #         single_processors["{}_{}".format(key, p_key)] = lambda ndx, row: key_processor[p_key](row[key])

    # def processor(ndx, row):
    #     return {key:single_processors[key](ndx, row) for key in single_processors}

    # new_col_fns = {}
    # if isinstance(example_input, dict):
    #     for key in example_input:
    #         processor_dict = _infer_validation_input_processor_dict(example_input[key])

    # def processor(ndx, row):
    #     return {
    #         col:new_col_fns[col](ndx, row) for col in new_col_fns
    #     }

    # return processor


def _infer_prediction_row_processor(
    example_prediction: Union[Dict, Iterator],
    example_input: Union[Dict, Iterator],
    example_target: Union[Dict, Iterator, Any],
    class_labels_table: Optional["wandb.Table"] = None,
):
    return None
    # def processor(ndx, row):
    #     return {
    #         col:new_col_fns[col](ndx, row) for col in new_col_fns
    #     }

    # return processor
