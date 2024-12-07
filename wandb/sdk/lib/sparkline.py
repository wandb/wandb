#
# From pysparklines (BSD License): https://pypi.python.org/pypi/pysparklines

import math
from typing import List, Union

spark_chars = "▁▂▃▄▅▆▇█"


# math.isfinite doesn't exist in python2, so provider our own
def isfinite(f):
    return not (math.isinf(f) or math.isnan(f))


def sparkify(series: List[Union[float, int]]) -> str:
    """Convert <series> to a sparkline string.

    Example:
    >>> sparkify([0.5, 1.2, 3.5, 7.3, 8.0, 12.5, 13.2, 15.0, 14.2, 11.8, 6.1, 1.9])
    u'▁▁▂▄▅▇▇██▆▄▂'

    >>> sparkify([1, 1, -2, 3, -5, 8, -13])
    u'▆▆▅▆▄█▁'

    Raises ValueError if input data cannot be converted to float.
    Raises TypeError if series is not an iterable.
    """
    series = [float(i) for i in series]
    finite_series = [x for x in series if isfinite(x)]
    if not finite_series:
        return ""
    minimum = min(finite_series)
    maximum = max(finite_series)
    data_range = maximum - minimum
    if data_range == 0.0:
        # Graph a baseline if every input value is equal.
        return "".join([spark_chars[0] if isfinite(x) else " " for x in series])
    coefficient = (len(spark_chars) - 1.0) / data_range
    return "".join(
        [
            spark_chars[int(round((x - minimum) * coefficient))] if isfinite(x) else " "
            for x in series
        ]
    )
