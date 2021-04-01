# wandb.integrations.data_logging.py
#
# Contains common utility functions that enable
# logging datasets and predictions to wandb.

"""
Usage:

# epoch-level evaluations (no dataset) - implicit processors

x_npy, y_npy = load_dataset()
model.fit(x_npy, y_npy, callbacks=[WandbCallback(
    log_evaluation=True
)])

# epoch-level evaluations (no dataset) - explicit processors

x_npy, y_npy = load_dataset()
class_table = table_from_iterables([("name", ["dog", "cat", "mouse"])])
model.fit(x_npy, y_npy, callbacks=[WandbCallback(
    log_evaluation=True
    val_x_proccessors=[{"img": wandb.Image}],
    val_y_proccessors=[{"class_details": lambda x: class_table.index_ref(x)}],
    output_proccessors = [{
        "class_details": lambda x: ds["classes"].index_ref(np.argmax(x)),
        "class_score": lambda x: {c_name:c_score for c_name, c_score in zip(ds["classes"].get_column("name"), x.to_list())}
    }]
)])

# Manually log evaluation results w/o dataset, including processors

x_npy, y_npy = load_dataset()
(x_train, x_test,
y_train, y_test) = train_test_split(x_npy, y_npy)

model.fit(x_train, y_train)

class_table = table_from_iterables([("name", ["dog", "cat", "mouse"])])
eval_results = table_from_iterables([
    ("input": x_test, {"img": wandb.Image}),
    ("target": y_test, {"class_details": lambda x: class_table.index_ref(x)}),
    ("output": model.predict(x_test), {
        "class_details": lambda x: ds["classes"].index_ref(np.argmax(x)),
        "class_score": lambda x: {c_name:c_score for c_name, c_score in zip(ds["classes"].get_column("name"), x.to_list())}
    })
])

run.log({"eval_results": eval_results})


# Build a dataset

x_npy, y_npy = load_dataset()
class_table = table_from_iterables([("name", ["dog", "cat", "mouse"])])
train_table = table_from_iterables([
    ("x", x_npy, {"img": wandb.Image})
    ("y", y_npy, {"class_details": lambda x: class_table.index_ref(x)})
])
ds = log_dataset_artifact("example", [
    ("classes", class_table),
    ("train_data", train_table)
])

# epoch-level evaluations (w/ dataset) - implicit processors

ds = run.use_artifact("example_dataset:latest")
x_npy, y_npy, ndx = (
    ds["train_data"].get_column("x", convert_to="numpy"),
    ds["train_data"].get_column("y", convert_to="numpy"),
    ds["train_data"].get_index())
(x_train, x_test,
y_train, y_test,
n_train, n_test) = train_test_split(x_npy, y_npy, ndx)
model.fit(x_train, y_train, callbacks=[WandbCallback(
    log_evaluation=True,
    eval_index=n_test,
)])

# epoch-level evaluations (w/ dataset) - explicit processors

ds = run.use_artifact("example_dataset:latest")
x_npy, y_npy, ndx = (
    ds["train_data"].get_column("x", convert_to="numpy"),
    ds["train_data"].get_column("y", convert_to="numpy"),
    ds["train_data"].get_index())
(x_train, x_test,
y_train, y_test,
n_train, n_test) = train_test_split(x_npy, y_npy, ndx)
model.fit(x_train, y_train, callbacks=[WandbCallback(
    log_evaluation=True,
    eval_index=n_test,
    output_proccessors = [{
        "class_details": lambda x: ds["classes"].index_ref(np.argmax(x)),
        "class_score": lambda x: {c_name:c_score for c_name, c_score in zip(ds["classes"].get_column("name"), x.to_list())}
    }]
)])

# Manually log evaluation results against a dataset

ds = run.use_artifact("example_dataset:latest")
x_npy, y_npy, ndx = (
    ds["train_data"].get_column("x", convert_to="numpy"),
    ds["train_data"].get_column("y", convert_to="numpy"),
    ds["train_data"].get_index())
(x_train, x_test,
y_train, y_test,
n_train, n_test) = train_test_split(x_npy, y_npy, ndx)

model.fit(x_train, y_train)

eval_results = table_from_iterables([
    ("example_ndx": n_test),
    ("prediction": model.predict(x_test), {
        "class_details": lambda x: ds["classes"].index_ref(np.argmax(x)),
        "class_score": lambda x: {c_name:c_score for c_name, c_score in zip(ds["classes"].get_column("name"), x.to_list())}
    })
])

run.log({"eval_results": eval_results})


"""

import wandb

# # from wandb.util import is_numpy_array, is_pytorch_tensor, is_tf_tensor

if wandb.TYPE_CHECKING:

    from typing import TYPE_CHECKING, Any, Callable, Dict, Union, Tuple

    if TYPE_CHECKING:
        #         # import numpy as np
        from collections.abc import Iterator

#         _ProcessorFnType = Callable
#         _PossibleIterableColumnProcessorType = Union[
#             "_IterableColumnProcessor", _ProcessorFnType
#         ]
#         _PossibleIterableColumn = Union[
#             "_IterableColumn",
#             Tuple[str, Iterator],
#             Tuple[str, Iterator, Dict[str, _PossibleIterableColumnProcessorType]],
#         ]


# def _is_iterable(obj: Any) -> bool:
#     return hasattr(obj, "__iter__") and hasattr(obj, "__next__")


# def is_valid_processors_param(obj: any) -> bool:
#     return isinstance(obj, dict) and all(
#         isinstance(obj[k], _IterableColumnProcessor) or isinstance(obj[k], callable)
#         for k in obj
#     )


# def is_valid_columns_param(obj: any) -> bool:
#     assert isinstance(obj, list) and all(
#         (
#             isinstance(item, _IterableColumn)
#             or (
#                 isinstance(item, tuple)
#                 and len(item) >= 2
#                 and isinstance(item[0], str)
#                 and _is_iterable(item[1])
#                 and (len(item) == 2 or is_valid_processors_param(obj[k][2]))
#             )
#         )
#         for item in obj
#     )


# class _IterableColumnProcessor(object):
#     _name: str
#     _processor_fn: _ProcessorFnType

#     def __init__(self, name: str, processor_fn: _ProcessorFnType) -> None:
#         assert isinstance(name, str)
#         assert isinstance(processor_fn, callable)
#         self._name = name
#         self._processor_fn = processor_fn


# class _IterableColumn(object):
#     _name: str
#     _iterable: Iterator
#     _processors: Dict[str, _IterableColumnProcessor]

#     def __init__(
#         self,
#         name: str,
#         iterable: Iterator,
#         processors: Dict[str, "_PossibleIterableColumnProcessorType"],
#     ) -> None:
#         assert isinstance(name, str)
#         assert _is_iterable(iterable)
#         assert is_valid_processors_param(processors)

#         self._name = name
#         self._iterable = iterable
#         for k in processors:
#             if isinstance(processors[k], callable):
#                 processors[k] = _IterableColumnProcessor(k, processors[k])
#         self._processors = processors

#     def get_data(self) -> Dict[str, Iterator]:
#         res: Dict[str, Iterator]
#         res = {}
#         res[self._name] = self._iterable
#         for processor_name in self._processors:
#             processed = []
#             for item in self._iterable:
#                 processed.append(self._processors[processor_name](item))
#             res["{}_{}".format(self._name, processor_name)] = processed
#         return res


# def table_from_iterables(columns: List[_PossibleIterableColumn]):
#     """

#     Usage:
#     table_from_iterables([
#         ("x", x_npy, {"img" wandb.Image}),
#         ("y", y_npy, {"label": lambda y_val: ["dog", "cat", "fish"][np.argmax(y_val)]})
#     ])
#     """
#     assert is_valid_columns_param(columns)
#     table = wandb.Table(columns=[], data=[])
#     for col in columns:
#         if isinstance(col, tuple):
#             col = _IterableColumn(*tuple)
#         col_data = col.get_data()
#         for col_inner_name in col_data:
#             table.add_column(col_inner_name, col_data[col_inner_name])
#     return table


# def log_dataset_artifact(
#     dataset_name: str,
#     tables: List[Tuple[str, wandb.wandb_sdk.data_types.Table]],
#     dataset_type: str = "dataset",
# ) -> wandb.wandb_sdk.data_types.Table:

#     assert isinstance(dataset_name, str)
#     assert isinstance(tables, list) and all(
#         isinstance(t[0], str) and isinstance(t[1], wandb.wandb_sdk.data_types.Table)
#         for t in tables
#     )
#     assert isinstance(dataset_type, str)

#     ds_name = (
#         "{}_{}".format(dataset_name, dataset_type)
#         if not dataset_name.endswith(dataset_type)
#         else dataset_name
#     )
#     art = wandb.Artifact(ds_name, dataset_type)
#     for table_name in tables:
#         art.add(tables[table_name], table_name)
#     art.save()
#     return art


# class PredictionLogger(object):
#     pass


def generate_processor_from_label(label: str):
    # TODO: bring over the logic to map "image", etc... to a processor
    def processor(ndx, row):
        return {}

    return processor


def generate_processor_from_shape(shape: Tuple):
    # TODO: bring over the logic to infer from shape
    def processor(ndx, row):
        return {}

    return processor


def generate_processor_from_example(example: Any):
    # TODO: bring over the logic to infer from specific example
    def processor(ndx, row):
        return {}

    return processor


class ValidationDataLogger(object):
    def __init__(
        self,
        inputs: Union[Iterator, Dict[Iterator]],
        targets: Optional[Union[Iterator, Dict[Iterator]]] = None,
        indexes: Optional[List[wadnb.wandb_sdk.data_types._TableIndex]] = None,
        validation_row_processor: Optional[Callable] = None,
        prediction_row_processor: Optional[Callable] = None,
        input_col_name="input",
        target_col_name="target",
        table_name="wb_validation_data",
        artifact_type="validation_dataset",
    ):
        if indexes is None:
            assert targets is not None
            local_validation_table = wandb.Table(columns=[], data=[])
            if isinstance(inputs, dict):
                for col_name in inputs:
                    local_validation_table.add_col(col_name, inputs[col_name])
            else:
                local_validation_table.add_col(input_col_name, inputs)

            if isinstance(targets, dict):
                for col_name in targets:
                    local_validation_table.add_col(col_name, targets[col_name])
            else:
                local_validation_table.add_col(target_col_name, targets)

            if validation_row_processor is not None:
                local_validation_table.add_computed_columns(validation_row_processor)

            self._local_validation_artifact = wandb.Artifact(table_name, artifact_type)
            self._local_validation_artifact.add(
                local_validation_table, "validation_data"
            )
            wandb.run.use_artifact(self._local_validation_artifact)
            indexes = self._local_validation_artifact.get_index()
        else:
            self._local_validation_artifact = None

        self.validation_inputs = inputs
        self.validation_indexes = indexes
        self.prediction_row_processor = prediction_row_processor

    def make_predictions(self, predict_fn):
        return predict_fn(self.validation_inputs)

    def log_predictions(
        self,
        predictions: Union[Iterator, Dict[Iterator]],
        prediction_col_name="output",
        val_ndx_col_name="val_ndx",
        table_name="validation_predictions",
        commit=False,
    ):
        if self._local_validation_artifact is not None:
            self._local_validation_artifact.wait()

        pred_table = wandb.Table(columns=[], data=[])
        pred_table.add_column(val_ndx_col_name, self.validation_indexes)
        if isinstance(predictions, dict):
            for col_name in predictions:
                self.pred_table.add_col(col_name, predictions[col_name])
        else:
            self.pred_table.add_col(prediction_col_name, predictions)

        if self.prediction_row_processor is not None:
            self._local_validation_table.add_computed_columns(
                self.prediction_row_processor
            )

        wandb.log({table_name: self._local_validation_table})
