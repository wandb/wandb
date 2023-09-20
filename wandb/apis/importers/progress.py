import atexit

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


class TaskProgressWithCountColumn(ProgressColumn):
    def render(self, task) -> Text:
        if task.total is None:
            message = "in progress..."
        else:
            message = f"{task.percentage:>3.0f}% ({task.completed}/{task.total})"

        text = Text()
        text.append(message, style="magenta")
        return text


def progress_bar():
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressWithCountColumn(),
        TimeElapsedColumn(),
        expand=True,
    )


task_pbar = progress_bar()
overall_time = task_pbar.add_task("Importing...", total=None)

subtask_pbar = progress_bar()
subsubtask_pbar = progress_bar()

table = Table().grid()
table.add_row(
    Panel(
        task_pbar,
        title="W&B Importer (see `importer.log` for logs)",
        padding=(1, 2),
        style=Style(bold=True),
    )
)
# table.add_column("subsubtask")
table.add_row(Panel(subtask_pbar, title="Subtasks", padding=(1, 2)))
table.add_row(Panel(subsubtask_pbar, title="Sub-subtasks", padding=(1, 2)))

# table = Table().grid()
# table.add_column("subsubtask")
# table.add_column("subsubtask2")
# table.add_row(
#     Panel(
#         task_pbar,
#         title="W&B Importer (see `importer.log` for logs)",
#         padding=(1, 2),
#         style=Style(bold=True),
#     ),
# )
# table.add_row(
#     Panel(subtask_pbar, title="Subtasks", padding=(1, 2)),
#     Panel(subsubtask_pbar, title="Sub-subtasks", padding=(1, 2)),
# )


live = Live(table, refresh_per_second=10)


def cleanup():
    with live:
        task_pbar.update(overall_time, completed=1, total=1)


atexit.register(cleanup)
