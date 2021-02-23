import wandb

# from wandb import util

from ...data_types import Table

if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING, Optional, Sequence, List

    if TYPE_CHECKING:
        import numpy as np  # type: ignore


class NDArrayConverter:
    def convert(self, val: "np.ndarray") -> List:
        raise NotImplementedError(
            "{}.convert is not implemented".format(self.__class__.__name__)
        )

    # def convert_x(
    #     self, x: "np.ndarray", y_pred: "np.ndarray", y_true: "np.ndarray"
    # ) -> List:
    #     return self.convert(x)

    # def convert_y_pred(
    #     self, x: "np.ndarray", y_pred: "np.ndarray", y_true: "np.ndarray"
    # ) -> List:
    #     return self.convert(y_pred)

    # def convert_y_true(
    #     self, x: "np.ndarray", y_pred: "np.ndarray", y_true: "np.ndarray"
    # ) -> List:
    #     return self.convert(y_true)


class IdentityConverter(NDArrayConverter):
    def convert(self, val: "np.ndarray") -> List:
        return val.tolist()


class RGBImageConverter(NDArrayConverter):
    def convert(self, val: "np.ndarray") -> List:
        return [wandb.Image(val)]


class ArgmaxConverter(NDArrayConverter):
    def convert(self, val: "np.ndarray") -> List:
        return [val.argmax().tolist()]


def infer_single_converter(arr: "np.ndarray") -> Optional[NDArrayConverter]:
    # TODO: Infer from shape and type / expose customization to the user

    # Infer simple image
    if len(arr.shape) == 3 and arr.shape[2] == 3:
        return RGBImageConverter()

    if len(arr.shape) == 1 and arr.shape[0] < 100:
        return IdentityConverter()

    return None


def infer_target_converter(
    yp: "np.ndarray", yt: "np.ndarray"
) -> Optional[NDArrayConverter]:
    # TODO: Infer from shape and type

    # Infer Argmax
    if (
        len(yt.shape) == 1
        and yt.shape[0] == 1
        and len(yp.shape) == 1
        and yp.shape[0] > 1
    ):
        return ArgmaxConverter()

    return None


def infer_labels(arr: "np.ndarray", suffix: str = "") -> List[str]:
    return ["{}{}".format(i, suffix) for i in range(len(arr))]


def validation_table(
    x: "np.ndarray",
    y_true: "np.ndarray",
    x_labels: Optional[Sequence[str]] = None,
    y_true_labels: Optional[Sequence[str]] = None,
    x_converter: Optional[NDArrayConverter] = None,
    y_true_converter: Optional[NDArrayConverter] = None,
) -> Optional[Table]:
    # np = util.get_module("numpy", required="Validation table requires numpy")

    if len(x) == 0 or len(x) != len(y_true):
        return None

    if x_converter is None:
        x_converter = infer_single_converter(x[0])

    if y_true_converter is None:
        y_true_converter = infer_single_converter(y_true[0])

    if x_converter is None or y_true_converter is None:
        return None

    data = []
    ndx = 0
    for x_row, y_true_row in zip(x, y_true):
        row = [ndx] + y_true_converter.convert(y_true_row) + x_converter.convert(x_row)
        ndx += 1
        data.append(row)

    if x_labels is None:
        x_labels = infer_labels(x_converter.convert(x_row), "_x")

    if y_true_labels is None:
        y_true_labels = infer_labels(y_true_converter.convert(y_true_row), "_true")

    columns = ["ndx"] + list(y_true_labels) + list(x_labels)

    return Table(columns=columns, data=data, allow_mixed_types=True)


def validation_results(
    x: "np.ndarray",
    y_pred: "np.ndarray",
    y_true: "np.ndarray",
    x_labels: Optional[Sequence[str]] = None,
    y_pred_labels: Optional[Sequence[str]] = None,
    x_converter: Optional[NDArrayConverter] = None,
    y_pred_converter: Optional[NDArrayConverter] = None,
) -> Optional[Table]:
    # np = util.get_module("numpy", required="Validation table requires numpy")

    if len(x) == 0 or len(x) != len(y_pred):
        return None

    target_converter = None
    if y_pred_converter is None:
        y_pred_converter = infer_single_converter(y_pred[0])
        target_converter = infer_target_converter(y_pred[0], y_true[0])

    if y_pred_converter is None:
        return None

    data = []
    ndx = 0
    for y_pred_row in y_pred:
        t = []
        if target_converter:
            t = target_converter.convert(y_pred_row)
        row = [ndx] + t + y_pred_converter.convert(y_pred_row)
        ndx += 1
        data.append(row)

    if y_pred_labels is None:
        y_pred_labels = infer_labels(y_pred_converter.convert(y_pred_row), "_pred")
        if target_converter:
            y_pred_labels = ["summary_pred"] + y_pred_labels

    columns = ["ndx"] + list(y_pred_labels)

    return Table(columns=columns, data=data, allow_mixed_types=True)


# def default_validation_table(
#     x: "np.ndarray",
#     y_pred: "np.ndarray",
#     y_true: "np.ndarray",
#     x_labels: Optional[Sequence[str]] = None,
#     y_pred_labels: Optional[Sequence[str]] = None,
#     y_true_labels: Optional[Sequence[str]] = None,
#     x_converter: Optional[NDArrayConverter] = None,
#     y_pred_converter: Optional[NDArrayConverter] = None,
#     y_true_converter: Optional[NDArrayConverter] = None,
# ) -> Optional[Table]:
#     # np = util.get_module("numpy", required="Validation table requires numpy")

#     if len(x) == 0 or len(x) != len(y_pred) != len(y_true):
#         return None

#     if x_converter is None:
#         x_converter = infer_single_converter(x[0])

#     if y_true_converter is None:
#         y_true_converter = infer_single_converter(y_true[0])

#     target_converter = None
#     if y_pred_converter is None:
#         y_pred_converter = infer_single_converter(y_pred[0])
#         target_converter = infer_target_converter(y_pred[0], y_true[0])

#     if x_converter is None or y_true_converter is None or y_pred_converter is None:
#         return None

#     data = []
#     for zip_row in zip(x, y_pred, y_true):
#         t = []
#         if target_converter:
#             t = target_converter.convert_y_pred(*zip_row)
#         row = (
#             y_pred_converter.convert_y_pred(*zip_row)
#             + t
#             + y_true_converter.convert_y_true(*zip_row)
#             + x_converter.convert_x(*zip_row)
#         )
#         data.append(row)

#     if x_labels is None:
#         x_labels = infer_labels(x_converter.convert_x(*zip_row), "_x")

#     if y_pred_labels is None:
#         y_pred_labels = infer_labels(y_pred_converter.convert_y_pred(*zip_row), "_pred")
#         if target_converter:
#             y_pred_labels += ["summary_pred"]

#     if y_true_labels is None:
#         y_true_labels = infer_labels(y_true_converter.convert_y_true(*zip_row), "_true")

#     columns = list(y_pred_labels) + list(y_true_labels) + list(x_labels)

#     return Table(columns=columns, data=data, allow_mixed_types=True)
