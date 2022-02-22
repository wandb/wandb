import sys
from typing import Iterable, Optional, Sequence, Tuple, TYPE_CHECKING, Union

from wandb.util import get_module

from ._wandb_value import WBValue

if TYPE_CHECKING:
    import numpy as np  # type: ignore

    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run

    NumpyHistogram = Tuple[np.ndarray, np.ndarray]


class Histogram(WBValue):
    """wandb class for histograms.

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Examples:
        Generate histogram from a sequence
        ```python
        wandb.Histogram([1,2,3])
        ```

        Efficiently initialize from np.histogram.
        ```python
        hist = np.histogram(data)
        wandb.Histogram(np_histogram=hist)
        ```

    Arguments:
        sequence: (array_like) input data for histogram
        np_histogram: (numpy histogram) alternative input of a precomputed histogram
        num_bins: (int) Number of bins for the histogram.  The default number of bins
            is 64.  The maximum number of bins is 512

    Attributes:
        bins: ([float]) edges of bins
        histogram: ([int]) number of elements falling in each bin
    """

    _MAX_LENGTH: int = 512
    _log_type = "histogram"

    def __init__(
        self,
        data: Optional[Sequence] = None,
        np_histogram: Optional["NumpyHistogram"] = None,
        **kwargs,
    ) -> None:

        if data is not None:
            np = get_module(
                "numpy",
                required="wandb.Histogram requires numpy for auto generation. To install run: `pip install numpy`",
            )

            kwargs["bins"] = kwargs.pop("num_bins", 64)
            histogram, bins = np.histogram(data, **kwargs)
            histogram, bins = histogram.tolist(), bins.tolist()

        elif np_histogram is not None:
            if len(np_histogram) != 2:
                raise ValueError(
                    "Expected np_histogram to be a tuple of (values, bin_edges) or sequence to be specified"
                )
            if not isinstance(np_histogram[0], Iterable):
                raise TypeError(
                    f"`np_histogram[0]` is expected to be Iteralbe got {type(np_histogram[0])}"
                )
            if not isinstance(np_histogram[1], Iterable):
                raise TypeError(
                    f"`np_histogram[1]` is expected to be Iteralbe got {type(np_histogram[1])}"
                )
            histogram, bins = np_histogram

        else:
            raise RuntimeError(
                "Expected either `sequence` or `histogram`, but both are None"
            )

        if len(histogram) > self._MAX_LENGTH:
            raise ValueError(f"The maximum length of a histogram is {self._MAX_LENGTH}")

        if len(histogram) + 1 != len(bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

        self._hist, self._bins = histogram, bins

    def to_json(self, run: Union["Run", "Artifact"] = None) -> dict:
        return {
            "_type": self._log_type,
            "values": self._hist,
            "bins": self._bins,
        }

    def __sizeof__(self) -> int:
        """This returns an estimated size in bytes, currently the factor of 1.7
        is used to account for the JSON encoding.  We use this in tb_watcher.TBHistory
        """
        return int((sys.getsizeof(self._hist) + sys.getsizeof(self._bins)) * 1.7)
