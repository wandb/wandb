import sys

from .base import GraphQLError

__all__ = ['GraphQLLocatedError']


class GraphQLLocatedError(GraphQLError):

    def __init__(self, nodes, original_error=None):
        if original_error:
            try:
                message = str(original_error)
            except UnicodeEncodeError:
                message = original_error.message.encode('utf-8')
        else:
            message = 'An unknown error occurred.'

        if hasattr(original_error, 'stack'):
            stack = original_error.stack
        else:
            stack = sys.exc_info()[2]

        super(GraphQLLocatedError, self).__init__(
            message=message,
            nodes=nodes,
            stack=stack
        )
        self.original_error = original_error
