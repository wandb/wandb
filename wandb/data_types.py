class Histogram(object):
    MAX_LENGTH = 512

    def __init__(self, list_or_tuple, num_bins=64):
        """Accepts a tuple of (values, bins_edges) as np.histogram returns i.e.

        wandb.log({"histogram": wandb.Histogram(np.histogram(data))})

        Or a list of values in which case they will be automatically binned into num_bins.
        The maximum number of bins currently supported is 512
        """
        if isinstance(list_or_tuple, tuple) and len(list_or_tuple) == 2:
            self.histogram = list_or_tuple[0]
            self.bins = list_or_tuple[1]
        else:
            try:
                import numpy as np
            except ImportError:
                raise ValueError(
                    "Auto creation of histograms requires numpy")
            self.histogram, self.bins = np.histogram(
                list_or_tuple, bins=num_bins)
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(
                "The maximum length of a histogram is %i" % MAX_LENGTH)
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    @staticmethod
    def transform(histogram):
        return {"_type": "histogram", "values": histogram.histogram, "bins": histogram.bins}
