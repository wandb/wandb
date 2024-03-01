import logging
import sys
import traceback
from functools import wraps

import click
from click.exceptions import ClickException

from wandb import Error, termerror
from wandb.cli.utils.logger import get_wandb_cli_log_path

logger = logging.getLogger(__name__)


class ClickWandbException(ClickException):
    def format_message(self):
        # log_file = util.get_log_file_path()
        log_file = ""
        orig_type = f"{self.orig_type.__module__}.{self.orig_type.__name__}"
        if issubclass(self.orig_type, Error):
            return click.style(str(self.message), fg="red")
        else:
            return (
                f"An Exception was raised, see {log_file} for full traceback.\n"
                f"{orig_type}: {self.message}"
            )


def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.error("".join(lines))
            termerror(f"Find detailed error logs at: {get_wandb_cli_log_path()}")
            click_exc = ClickWandbException(e)
            click_exc.orig_type = exc_type
            raise click_exc.with_traceback(sys.exc_info()[2])

    return wrapper
