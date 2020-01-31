import click
import sys


LOG_STRING = click.style('wandb', fg='blue', bold=True)
ERROR_STRING = click.style('ERROR', bg='red', fg='green')
WARN_STRING = click.style('WARNING', fg='yellow')
PRINTED_MESSAGES = set()


def termlog(string='', newline=True, repeat=True):
    """Log to standard error with formatting.

    Args:
            string (str, optional): The string to print
            newline (bool, optional): Print a newline at the end of the string
            repeat (bool, optional): If set to False only prints the string once per process
    """
    if string:
        line = '\n'.join(['{}: {}'.format(LOG_STRING, s)
                          for s in string.split('\n')])
    else:
        line = ''
    if not repeat and line in PRINTED_MESSAGES:
        return
    # Repeated line tracking limited to 1k messages
    if len(PRINTED_MESSAGES) < 1000:
        PRINTED_MESSAGES.add(line)
    click.echo(line, file=sys.stderr, nl=newline)


def termwarn(string, **kwargs):
    string = '\n'.join(['{} {}'.format(WARN_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True, **kwargs)


def termerror(string, **kwargs):
    string = '\n'.join(['{} {}'.format(ERROR_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True, **kwargs)

