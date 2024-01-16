# import functools
# from contextlib import contextmanager
# from typing import Optional

# from rich.console import Console
# from rich.live import Live  # type: ignore
# from rich.panel import Panel  # type: ignore
# from rich.progress import (  # type: ignore
#     BarColumn,
#     Progress,
#     ProgressColumn,
#     TextColumn,
#     TimeElapsedColumn,
# )
# from rich.style import Style  # type: ignore
# from rich.table import Table  # type: ignore
# from rich.text import Text  # type: ignore
# from rich.traceback import install

# install()
# console = Console()


# class TaskProgressWithCountColumn(ProgressColumn):
#     def render(self, task) -> Text:
#         if task.total is None:
#             message = "in progress..."
#         else:
#             message = f"{task.percentage:>3.0f}% ({task.completed}/{task.total})"

#         text = Text()
#         text.append(message, style="magenta")
#         return text


# def progress_bar(transient=False):
#     return Progress(
#         TextColumn("[progress.description]{task.description}"),
#         BarColumn(),
#         TaskProgressWithCountColumn(),
#         TimeElapsedColumn(),
#         expand=True,
#         transient=transient,
#     )


# task_pbar = progress_bar(transient=False)
# overall_time = task_pbar.add_task("Importing...", total=None)

# subtask_pbar = progress_bar(transient=True)
# subsubtask_pbar = progress_bar(transient=True)

# table = Table().grid()
# table.add_row(
#     Panel(
#         task_pbar,
#         title="W&B Importer (see `importer.log` for logs)",
#         padding=(1, 2),
#         style=Style(bold=True),
#     )
# )
# table.add_row(Panel(subtask_pbar, title="Subtasks", padding=(1, 2)))
# table.add_row(Panel(subsubtask_pbar, title="Sub-subtasks", padding=(1, 2)))

# live = Live(table, refresh_per_second=10)


# # def cleanup():
# #     with live:
# #         task_pbar.update(overall_time, completed=1, total=1)


# # atexit.register(cleanup)


# def with_progress(f):
#     @functools.wraps(f)
#     def wrapper(*args, **kwargs):
#         live.start()
#         return f(*args, **kwargs)

#     return wrapper


# def progress(
#     iterable,
#     *,
#     pbar: Progress,
#     description: str = "",
#     total: Optional[int] = None,
#     transient: bool = False,
# ):
#     if total is None:
#         try:
#             total = len(iterable)
#         except Exception:
#             pass

#     task = pbar.add_task(description, total=total)
#     c = 0
#     try:
#         for x in iterable:
#             c += 1
#             yield x

#             if total is not None:
#                 pbar.update(task, advance=1)
#             else:
#                 pbar.update(task, description=description + f" ({c}/???)")
#     finally:
#         if transient:
#             pbar.remove_task(task)
#         else:
#             pbar.update(task, total=c, completed=c, description=description)


# task_progress = functools.partial(progress, pbar=task_pbar)
# subtask_progress = functools.partial(progress, pbar=subtask_pbar, transient=True)
# subsubtask_progress = functools.partial(progress, pbar=subsubtask_pbar, transient=True)


# @contextmanager
# def _track_task(description: str, *, pbar: Progress):
#     t = pbar.add_task(description)
#     try:
#         yield
#     finally:
#         pbar.remove_task(t)


# track_task = functools.partial(_track_task, pbar=task_pbar)
# track_subtask = functools.partial(_track_task, pbar=subtask_pbar)
# track_subsubtask = functools.partial(_track_task, pbar=subsubtask_pbar)


# def progress_decorator(description: Optional[str] = None, *, pbar: Progress):
#     def deco(f):
#         @functools.wraps(f)
#         def wrapper(*args, **kwargs):
#             desc = description or None
#             if desc is None:
#                 desc = f"{f.__name__}({args=}{kwargs=})"
#             else:
#                 arg_names = f.__code__.co_varnames[: f.__code__.co_argcount]
#                 args_kwargs = {**dict(zip(arg_names, args)), **kwargs}
#                 desc = description.format(**args_kwargs)

#             t = pbar.add_task(desc, total=None)
#             try:
#                 result = f(*args, **kwargs)
#             finally:
#                 pbar.remove_task(t)
#             return result

#         return wrapper

#     return deco


# task_progress_deco = functools.partial(progress_decorator, pbar=task_pbar)
# subtask_progress_deco = functools.partial(progress_decorator, pbar=subtask_pbar)
# subsubtask_progress_deco = functools.partial(progress_decorator, pbar=subsubtask_pbar)
