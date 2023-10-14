import atexit
import functools
from typing import Optional

from rich.console import Console
from rich.live import Live  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.progress import (  # type: ignore
    BarColumn,
    Progress,
    ProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.style import Style  # type: ignore
from rich.table import Table  # type: ignore
from rich.text import Text  # type: ignore
from rich.traceback import install

install()
console = Console()


class TaskProgressWithCountColumn(ProgressColumn):
    def render(self, task) -> Text:
        if task.total is None:
            message = "in progress..."
        else:
            message = f"{task.percentage:>3.0f}% ({task.completed}/{task.total})"

        text = Text()
        text.append(message, style="magenta")
        return text


def progress_bar(transient=False):
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressWithCountColumn(),
        TimeElapsedColumn(),
        expand=True,
        transient=transient,
    )


task_pbar = progress_bar(transient=False)
overall_time = task_pbar.add_task("Importing...", total=None)

subtask_pbar = progress_bar(transient=True)
subsubtask_pbar = progress_bar(transient=True)

table = Table().grid()
table.add_row(
    Panel(
        task_pbar,
        title="W&B Importer (see `importer.log` for logs)",
        padding=(1, 2),
        style=Style(bold=True),
    )
)
table.add_row(Panel(subtask_pbar, title="Subtasks", padding=(1, 2)))
table.add_row(Panel(subsubtask_pbar, title="Sub-subtasks", padding=(1, 2)))

live = Live(table, refresh_per_second=10)


def cleanup():
    with live:
        task_pbar.update(overall_time, completed=1, total=1)


atexit.register(cleanup)


def with_progress(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        live.start()
        return f(*args, **kwargs)

    return wrapper


def progress(
    iterable,
    *,
    pbar: Progress,
    description: str = "",
    total: Optional[int] = None,
    transient: bool = False,
):
    if total is None:
        try:
            total = len(iterable)
        except TypeError:
            pass

    task = pbar.add_task(description, total=total)
    c = 0
    try:
        for x in iterable:
            c += 1
            yield x

            if total is not None:
                pbar.update(task, advance=1)
            else:
                pbar.update(task, description=description + f" ({c}/???)")
    finally:
        if transient:
            pbar.remove_task(task)
        else:
            pbar.update(task, total=c, completed=c, description=description)


task_progress = functools.partial(progress, pbar=task_pbar)
subtask_progress = functools.partial(progress, pbar=subtask_pbar, transient=True)
subsubtask_progress = functools.partial(progress, pbar=subsubtask_pbar, transient=True)
