# vim: set fileencoding=utf-8 :
# From pysparklines (BSD License): https://pypi.python.org/pypi/pysparklines

spark_chars = u"▁▂▃▄▅▆▇█"

def sparkify(series):
    u"""Converts <series> to a sparkline string.
    
    Example:
    >>> sparkify([ 0.5, 1.2, 3.5, 7.3, 8.0, 12.5, 13.2, 15.0, 14.2, 11.8, 6.1,
    ... 1.9 ])
    u'▁▁▂▄▅▇▇██▆▄▂'

    >>> sparkify([1, 1, -2, 3, -5, 8, -13])
    u'▆▆▅▆▄█▁'

    Raises ValueError if input data cannot be converted to float.
    Raises TypeError if series is not an iterable.
    """
    series = [ float(i) for i in series ]
    minimum = min(series)
    maximum = max(series)
    data_range = maximum - minimum
    if data_range == 0.0:
        # Graph a baseline if every input value is equal.
        return u''.join([ spark_chars[0] for i in series ])
    coefficient = (len(spark_chars) - 1.0) / data_range
    return u''.join([
        spark_chars[
            int(round((x - minimum) * coefficient))
        ] for x in series
    ])