from ..language.location import get_location
from .base import GraphQLError

__all__ = ['GraphQLSyntaxError']


class GraphQLSyntaxError(GraphQLError):

    def __init__(self, source, position, description):
        location = get_location(source, position)
        super(GraphQLSyntaxError, self).__init__(
            message=u'Syntax Error {} ({}:{}) {}\n\n{}'.format(
                source.name,
                location.line,
                location.column,
                description,
                highlight_source_at_location(source, location),
            ),
            source=source,
            positions=[position],
        )


def highlight_source_at_location(source, location):
    line = location.line
    lines = source.body.splitlines()
    pad_len = len(str(line + 1))
    result = u''
    format = (u'{:>' + str(pad_len) + '}: {}\n').format
    if line >= 2:
        result += format(line - 1, lines[line - 2])
    result += format(line, lines[line - 1])
    result += ' ' * (1 + pad_len + location.column) + '^\n'
    if line < len(lines):
        result += format(line + 1, lines[line])
    return result
