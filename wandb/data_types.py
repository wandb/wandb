class Histogram(object):
    MAX_LENGTH = 512

    def __init__(self, list_or_tuple, bin_edges=None, num_bins=64):
        """Accepts a tuple of (values, bins_edges) as np.histogram returns, a list of values
        which will be automatically binned, or histogram and bin_edges passed separately. 
        len(bin_edges) must be len(histogram) + 1
        """
        if not bin_edges:
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
        else:
            self.histogram = list_or_tuple
            self.bins = bin_edges
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(
                "The maximum length of a histogram is %i" % MAX_LENGTH)
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    @staticmethod
    def transform(histogram):
        return {"_type": "histogram", "values": histogram.histogram, "bins": histogram.bins}
