import logging
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Namespace:
    """Configure an alternate entity/project at the dst server your data will end up in."""

    entity: str
    project: str

    @classmethod
    def from_path(cls, path: str):
        entity, project = path.split("/")
        return cls(entity, project)

    @property
    def path(self):
        return f"{self.entity}/{self.project}"

    @property
    def send_manager_overrides(self):
        overrides = {}
        if self.entity:
            overrides["entity"] = self.entity
        if self.project:
            overrides["project"] = self.project
        return overrides


logger = logging.getLogger("import_logger")


def parallelize(
    func,
    iterable: Iterable,
    *args,
    max_workers: Optional[int] = None,
    raise_on_error: bool = False,
    **kwargs,
):
    def safe_func(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _, _, exc_traceback = sys.exc_info()
            traceback_details = traceback.extract_tb(exc_traceback)
            filename = traceback_details[-1].filename
            lineno = traceback_details[-1].lineno
            logger.debug(
                f"Exception: {func=} {args=} {kwargs=} {e=} {filename=} {lineno=}. {traceback_details=}"
            )
            if raise_on_error:
                raise

    results = []
    with ThreadPoolExecutor(max_workers) as exc:
        futures = {exc.submit(safe_func, x, *args, **kwargs): x for x in iterable}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def for_each(
    func, iterable: Iterable, parallel: bool = True, max_workers: Optional[int] = None
):
    if parallel:
        return parallelize(
            func,
            iterable,
            max_workers=max_workers,
        )

    return [func(x) for x in iterable]
