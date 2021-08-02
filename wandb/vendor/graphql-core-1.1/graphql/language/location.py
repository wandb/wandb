__all__ = ['get_location', 'SourceLocation']


class SourceLocation(object):
    __slots__ = 'line', 'column'

    def __init__(self, line, column):
        self.line = line
        self.column = column

    def __repr__(self):
        return '<SourceLocation line={} column={}>'.format(self.line, self.column)

    def __eq__(self, other):
        return (
            isinstance(other, SourceLocation) and
            self.line == other.line and
            self.column == other.column
        )


def get_location(source, position):
    lines = source.body[:position].splitlines()
    if lines:
        line = len(lines)
        column = len(lines[-1]) + 1
    else:
        line = 1
        column = 1
    return SourceLocation(line, column)
