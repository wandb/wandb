import contextlib
import os
import sqlite3
from typing import (
    Any,
    Iterator,
    List,
    Optional,
    Tuple,
)

Migration = List[str]
Migrations = List[Migration]

Error = sqlite3.Error


@contextlib.contextmanager
def open_db(path: str) -> sqlite3.Connection:
    with sqlite3.connect(os.path.join(path)) as db:
        yield db


@contextlib.contextmanager
def txn(conn: sqlite3.Connection, is_exclusive=False):
    conn.execute(
        "BEGIN TRANSACTION" if not is_exclusive else "BEGIN EXCLUSIVE TRANSACTION"
    )
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def fetch(conn: sqlite3.Connection, sql: str, args: Tuple = ()) -> Iterator[Tuple]:
    cur = conn.cursor()
    for row in cur.execute(sql, args):
        yield row


def fetch_one(conn: sqlite3.Connection, sql: str, args: Tuple = ()) -> Any:
    cur = conn.cursor()
    cur.execute(sql, args)
    return cur.fetchone()


def migrate(conn: sqlite3.Connection, migrations: Migrations) -> None:
    with txn(conn, is_exclusive=True):
        (count,) = fetch_one(conn, """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE
                type ='table' AND
                name = ?
        """, ("schema_migrations",))
        if count == 0:
            # Primitive schema management, could eventually do something
            # more sophisticated.
            conn.execute(
                """
                CREATE TABLE schema_migrations(
                    version INTEGER PRIMARY KEY,
                    dirty BOOLEAN
                )
            """
            )

            conn.execute("""
                INSERT INTO schema_migrations (version) VALUES (0);
            """)

    with txn(conn, is_exclusive=True):
        (version,) = fetch_one(conn, "SELECT version FROM schema_migrations") or (0,)
        for migration_idx, migration in enumerate(migrations):
            if version > migration_idx:
                continue
            for stmt in migration:
                conn.execute(stmt)
            conn.execute(
                "UPDATE schema_migrations SET version = ?", (migration_idx + 1,)
            )
