import wandb

# from wandb import util

from ...data_types import Table

if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING, Optional, Callable, Sequence, List

    if TYPE_CHECKING:
        import numpy as np  # type: ignore


def default_validation_table(
    x: "np.ndarray",
    y_pred: "np.ndarray",
    y_true: "np.ndarray",
    x_labels: Optional[Sequence[str]] = None,
    y_pred_labels: Optional[Sequence[str]] = None,
    y_true_labels: Optional[Sequence[str]] = None,
    x_converter: Optional[Callable] = None,
    y_pred_converter: Optional[Callable] = None,
    y_true_converter: Optional[Callable] = None,
) -> Optional[Table]:
    # np = util.get_module("numpy", required="Validation table requires numpy")

    if len(x) == 0 or len(x) != len(y_pred) != len(y_true):
        return None

    if x_converter is None:
        x_converter = infer_single_converter(x[0])

    if y_true_converter is None:
        y_true_converter = infer_single_converter(y_true[0])

    target_converter = None
    if y_pred_converter is None:
        y_pred_converter = infer_single_converter(y_pred[0])
        target_converter = infer_target_converter(y_pred[0], y_true[0])

    if x_converter is None or y_true_converter is None or y_pred_converter is None:
        return None

    data = []
    for x_row, y_pred_row, y_true_row in zip(x, y_pred, y_true):
        t = []
        if target_converter:
            t = target_converter(y_pred_row)
        row = (
            y_pred_converter(y_pred_row)
            + t
            + y_true_converter(y_true_row)
            + x_converter(x_row)
        )
        data.append(row)

    if x_labels is None:
        x_labels = infer_labels(x_converter(x[0]), "_x")

    if y_pred_labels is None:
        y_pred_labels = infer_labels(y_pred_converter(y_pred[0]), "_pred")
        if target_converter:
            y_pred_labels += ["summary_pred"]

    if y_true_labels is None:
        y_true_labels = infer_labels(y_true_converter(y_true[0]), "_true")

    columns = list(y_pred_labels) + list(y_true_labels) + list(x_labels)

    return Table(columns=columns, data=data, allow_mixed_types=True)


def identity_converter(arr: "np.ndarray") -> List:
    return arr.tolist()


def rbg_image_converter(arr: "np.ndarray") -> List:
    return [wandb.Image(arr)]


def argmax_converter(arr: "np.ndarray") -> List:
    return [arr.argmax().tolist()]


def infer_single_converter(arr: "np.ndarray") -> Optional[Callable]:
    # TODO: Infer from shape and type

    # Infer simple image
    if len(arr.shape) == 3 and arr.shape[2] == 3:
        return rbg_image_converter

    if len(arr.shape) == 1 and arr.shape[0] < 100:
        return identity_converter

    return None


def infer_target_converter(yp: "np.ndarray", yt: "np.ndarray") -> Optional[Callable]:
    # TODO: Infer from shape and type

    # Infer Argmax
    if (
        len(yt.shape) == 1
        and yt.shape[0] == 1
        and len(yp.shape) == 1
        and yp.shape[0] > 1
    ):
        return argmax_converter

    return None


def infer_labels(arr: "np.ndarray", suffix: str = "") -> List[str]:
    return ["{}{}".format(i, suffix) for i in range(len(arr))]
