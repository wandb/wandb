from __future__ import annotations

import contextlib
import logging
import pathlib
from collections.abc import Iterator

from wandb.sdk.lib import wb_logging

wb_logging.configure_wandb_logger()


@contextlib.contextmanager
def _wandb_file_handler(
    run_id: str,
    path: pathlib.Path,
) -> Iterator[None]:
    handler = wb_logging.add_file_handler(run_id, path)
    try:
        yield
    finally:
        handler.close()
        logging.getLogger("wandb").removeHandler(handler)


def test_filters_log_messages(tmp_path: pathlib.Path):
    run1_log_path = tmp_path / "run1.log"
    run2_log_path = tmp_path / "run2.log"
    logger = logging.getLogger("wandb")

    with contextlib.ExitStack() as stack:
        stack.enter_context(_wandb_file_handler("run1", run1_log_path))
        stack.enter_context(_wandb_file_handler("run2", run2_log_path))

        logger.info("1: both runs")
        with wb_logging.log_to_run("run1"):
            logger.info("2: only run1")
            with wb_logging.log_to_run("run2"):
                logger.info("3: only run2")
            with wb_logging.log_to_all_runs():
                logger.info("4: both runs")
            logger.info("5: only run1")
            with wb_logging.log_to_run(None):
                logger.info("6: both runs")

    run1_lines = run1_log_path.read_text().splitlines()
    assert len(run1_lines) == 5
    assert run1_lines[0].endswith("] [no run ID] 1: both runs")
    assert run1_lines[1].endswith("] 2: only run1")
    assert run1_lines[2].endswith("] [all runs] 4: both runs")
    assert run1_lines[3].endswith("] 5: only run1")
    assert run1_lines[4].endswith("] [no run ID] 6: both runs")

    run2_lines = run2_log_path.read_text().splitlines()
    assert len(run2_lines) == 4
    assert run2_lines[0].endswith("] [no run ID] 1: both runs")
    assert run2_lines[1].endswith("] 3: only run2")
    assert run2_lines[2].endswith("] [all runs] 4: both runs")
    assert run2_lines[3].endswith("] [no run ID] 6: both runs")
