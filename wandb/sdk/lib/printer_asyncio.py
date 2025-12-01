import asyncio
from typing import Callable, TypeVar

from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat, printer

_T = TypeVar("_T")


def run_async_with_spinner(
    spinner_printer: printer.Printer,
    text: str,
    func: Callable[[], _T],
) -> _T:
    """Run a slow function while displaying a loading icon.

    Args:
        spinner_printer: The printer to use to display text.
        text: The text to display next to the spinner while the function runs.
        func: The function to run.

    Returns:
        The result of func.
    """

    async def _loop_run_with_spinner() -> _T:
        func_running = asyncio.Event()

        async def update_spinner() -> None:
            tick = 0
            with spinner_printer.dynamic_text() as text_area:
                if text_area:
                    while not func_running.is_set():
                        spinner = spinner_printer.loading_symbol(tick)
                        text_area.set_text(f"{spinner} {text}")
                        tick += 1
                        await asyncio.sleep(0.1)
                else:
                    spinner_printer.display(text)

        async with asyncio_compat.open_task_group() as group:
            group.start_soon(update_spinner())
            res = await asyncio.get_running_loop().run_in_executor(None, func)
            func_running.set()
            return res

    asyncer = wandb_setup.singleton().asyncer
    return asyncer.run(_loop_run_with_spinner)
