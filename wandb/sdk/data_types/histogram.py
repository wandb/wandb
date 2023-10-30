import sys
from typing import TYPE_CHECKING, Optional, Sequence, Tuple, Union

from wandb import util

from .base_types.wb_value import WBValue

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun

    NumpyHistogram = Tuple[np.ndarray, np.ndarray]


class Histogram(WBValue):
    """wandb class for histograms.

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Examples:
        Generate histogram from a sequence
        ```python
        wandb.Histogram([1, 2, 3])
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

    MAX_LENGTH: int = 512
    _log_type = "histogram"

    def __init__(
        self,
        sequence: Optional[Sequence] = None,
        np_histogram: Optional["NumpyHistogram"] = None,
        num_bins: int = 64,
    ) -> None:
        if np_histogram:
            if len(np_histogram) == 2:
                self.histogram = (
                    np_histogram[0].tolist()
                    if hasattr(np_histogram[0], "tolist")
                    else np_histogram[0]
                )
                self.bins = (
                    np_histogram[1].tolist()
                    if hasattr(np_histogram[1], "tolist")
                    else np_histogram[1]
                )
            else:
                raise ValueError(
                    "Expected np_histogram to be a tuple of (values, bin_edges) or sequence to be specified"
                )
        else:
            np = util.get_module(
                "numpy", required="Auto creation of histograms requires numpy"
            )

            self.histogram, self.bins = np.histogram(sequence, bins=num_bins)
            self.histogram = self.histogram.tolist()
            self.bins = self.bins.tolist()
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(
                "The maximum length of a histogram is %i" % self.MAX_LENGTH
            )
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    def to_json(self, run: Optional[Union["LocalRun", "Artifact"]] = None) -> dict:
        return {"_type": self._log_type, "values": self.histogram, "bins": self.bins}

    def __sizeof__(self) -> int:
        """Estimated size in bytes.

        Currently the factor of 1.7 is used to account for the JSON encoding. We use
        this in tb_watcher.TBHistory.
        """
        return int((sys.getsizeof(self.histogram) + sys.getsizeof(self.bins)) * 1.7)
