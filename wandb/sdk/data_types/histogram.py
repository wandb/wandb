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
    """W&B class for histograms.

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Attributes:
        bins ([float]): Edges of bins
        histogram  ([int]): Number of elements falling in each bin.
    """

    MAX_LENGTH: int = 512
    _log_type = "histogram"

    def __init__(
        self,
        sequence: Optional[Sequence] = None,
        np_histogram: Optional["NumpyHistogram"] = None,
        num_bins: int = 64,
    ) -> None:
        """Initialize a Histogram object.

        Args:
        sequence: Input data for histogram.
        np_histogram: Alternative input of a precomputed histogram.
        num_bins: Number of bins for the histogram.  The default number of bins
            is 64. The maximum number of bins is 512.

        Examples:
        Generate histogram from a sequence.

        ```python
        import wandb

        wandb.Histogram([1, 2, 3])
        ```

        Efficiently initialize from np.histogram.

        ```python
        import numpy as np
        import wandb

        hist = np.histogram(data)
        wandb.Histogram(np_histogram=hist)
        ```
        """
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

            histogram, bins = np.histogram(sequence, bins=num_bins)
            self.histogram = histogram.tolist()
            self.bins = bins.tolist()
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(f"The maximum length of a histogram is {self.MAX_LENGTH}")
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    def to_json(self, run: Optional[Union["LocalRun", "Artifact"]] = None) -> dict:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        return {"_type": self._log_type, "values": self.histogram, "bins": self.bins}

    def __sizeof__(self) -> int:
        """Estimated size in bytes.

        Currently the factor of 1.7 is used to account for the JSON encoding. We use
        this in tb_watcher.TBHistory.
        """
        return int((sys.getsizeof(self.histogram) + sys.getsizeof(self.bins)) * 1.7)
