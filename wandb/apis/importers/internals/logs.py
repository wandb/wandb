import logging
from collections import defaultdict

import wandb
from wandb.util import get_module

IMPORTER_LOG_FNAME = "importer.log"
IMPORTER_ISSUES_CSV_FNAME = "import_issues.csv"

pl = get_module(
    "polars",
    required="Missing `polars`, try `pip install polars`",
)


# class ThreadLocalFilter(logging.Filter):
#     def filter(self, record):
#         if not hasattr(record, "entity"):
#             record.entity = _thread_local_settings.src_entity

#         if not hasattr(record, "project"):
#             record.project = _thread_local_settings.src_project

#         if not hasattr(record, "run_id"):
#             record.run_id = _thread_local_settings.src_run_id

#         return True


# root_logger = logging.getLogger()
# fh = logging.FileHandler(IMPORTER_LOG_FNAME)
# formatter = logging.Formatter(
#     "%(asctime)s %(levelname)-8s %(entity)s/%(project)s/%(run_id)s [%(filename)s:%(lineno)d] %(message)s]"
# )
# fh.setFormatter(formatter)
# fh.addFilter(ThreadLocalFilter())
# root_logger.addHandler(fh)

# fh2 = logging.FileHandler(IMPORTER_ISSUES_CSV_FNAME)
# formatter2 = logging.Formatter(
#     "%(entity)s,%(project)s,%(run_id)s,%(levelname)s,%(message)s"
# )
# fh2.setFormatter(formatter2)
# fh2.addFilter(ThreadLocalFilter())
# root_logger.addHandler(fh2)

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

# wandb_logger = logging.getLogger("wandb.apis.importers.wandb")

import_logger = logging.getLogger("my_logger")
import_logger.setLevel(logging.DEBUG)  # Capture all log levels


def get_failed_imports():
    df = pl.read_csv(
        IMPORTER_ISSUES_CSV_FNAME,
        new_columns=["entity", "project", "run_id", "levelname", "message"],
    )
    unique_failed_imports = (
        df.filter(df["levelname"] == "ERROR")
        .select("entity", "project", "run_id")
        .unique()
    )

    d = defaultdict(list)
    for entity, project, run_id in unique_failed_imports.iter_rows():
        d[(entity, project)].append(run_id)

    return dict(d)


def print_failed_imports():
    failed_imports = get_failed_imports()
    if failed_imports:
        wandb.termerror(
            f"These data failed to import, see `{IMPORTER_LOG_FNAME}` and `{IMPORTER_ISSUES_CSV_FNAME}` for details."
        )
        for k, v in failed_imports.items():
            wandb.termerror(f"{k}: {v}")
