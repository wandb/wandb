import logging
import traceback
logger = logging.getLogger(__name__)


class CodeError(Exception):
    def __init__(self, message, code=None):
        self._code = code
        self.message = message
        super(Exception, self).__init__(message)

    @property
    def code(self):
        return self._code or 500


class PermissionError(CodeError):
    @property
    def code(self):
        return self._code or 403


class NotFoundError(CodeError):
    @property
    def code(self):
        return self._code or 404


class ValidationError(CodeError):
    @property
    def code(self):
        return self._code or 400


class ServerError(CodeError):
    @property
    def code(self):
        return self._code or 500


def format_error(self, error):
    """Ensure all graphql errors have an error code"""
    formatted_error = {
        'message': error.message,
        'code': 500,
    }
    methods = dir(error)
    logger.error(traceback.format_exc())
    if "locations" in methods and error.locations is not None:
        formatted_error['locations'] = [
            {'line': loc.line, 'column': loc.column}
            for loc in error.locations
        ]

    if "original_error" in methods:
        try:
            formatted_error['code'] = error.original_error.code
        except AttributeError:
            pass

    return formatted_error
