#!/usr/bin/env python
"""Export W&B run history.

This module uses the W&B public api to download unsampled history to a
sqlite database.

Usage:
    ./wandb_export_history --run entity/project/run_id --db_file save.db

or:
    ```python
    import wandb_export_history
    wandb_export_history(run="entity/project/run_id")
    ```

"""

import argparse
import sqlite3
from typing import Dict, Iterator, List

import pandas as pd  # type: ignore
import wandb

DB_FILE = "run.db"


def chunk(n: int, iterable) -> Iterator[List[Dict]]:
    done = False
    while not done:
        data = []
        try:
            for _ in range(n):
                data.append(next(iterable))
        except StopIteration:
            if data:
                yield data
            # done = True
            break
        yield data


def wandb_export_history(
    *,
    run,
    api=None,
    db_file=None,
    db_table=None,
    db_replace: bool = None,
    history_exclude_prefix=None,
    read_page_size=None,
    write_page_size=None,
) -> int:
    api = api or wandb.Api()
    db_file = db_file or DB_FILE
    db_table = db_table or "history"
    history_exclude_prefix = history_exclude_prefix or "system/"
    read_page_size = read_page_size or 1000
    write_page_size = write_page_size or 1000

    run = api.run(run)
    keys = run.history_keys.get("keys", [])
    if history_exclude_prefix:
        keys = list(filter(lambda x: not x.startswith(history_exclude_prefix), keys))

    db_file = db_file
    db = sqlite3.connect(db_file)

    history = run.scan_history(page_size=read_page_size)
    if_exists = "replace" if db_replace else "fail"
    written = 0
    for index, rows in enumerate(chunk(write_page_size, history)):
        df = pd.DataFrame.from_records(rows, **{} if index else dict(columns=keys))
        written += df.to_sql(
            "history", con=db, index=False, if_exists="append" if index else if_exists
        )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export W&B run history", allow_abbrev=False
    )
    parser.add_argument("--run", required=True)
    parser.add_argument("--db_file", default=DB_FILE)
    parser.add_argument("--db_table")
    parser.add_argument("--history_exclude_prefix")
    parser.add_argument("--read_page_size", type=int)
    parser.add_argument("--write_page_size", type=int)
    parser.add_argument("--db_replace", action="store_true")

    args = parser.parse_args()

    written = wandb_export_history(
        run=args.run,
        db_file=args.db_file,
        db_table=args.db_table,
        db_replace=args.db_replace,
        history_exclude_prefix=args.history_exclude_prefix,
        read_page_size=args.read_page_size,
        write_page_size=args.write_page_size,
    )
    print(f"Wrote {written} records to {args.db_file}")


if __name__ == "__main__":
    main()
