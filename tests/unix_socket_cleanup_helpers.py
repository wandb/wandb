"""Helpers for testing wandb-core Unix socket temp directory cleanup."""

from __future__ import annotations

import glob
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


def isolate_temp_dir(
    temp_root: Path,
    monkeypatch: Any,
) -> None:
    """Point Python and subprocess temp resolution at temp_root."""
    temp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TMPDIR", str(temp_root))
    monkeypatch.setenv("TEMP", str(temp_root))
    monkeypatch.setenv("TMP", str(temp_root))
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))


def isolated_temp_env(temp_root: Path) -> dict[str, str]:
    """Return env overrides for a subprocess with an isolated temp directory."""
    env = os.environ.copy()
    temp = str(temp_root)
    env["TMPDIR"] = temp
    env["TEMP"] = temp
    env["TMP"] = temp
    return env


def list_wandb_temp_entries(temp_root: Path) -> list[dict[str, Any]]:
    """Return wandb-* entries directly under temp_root with metadata."""
    entries: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(temp_root / "wandb*"))):
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISSOCK(st.st_mode):
            kind = "socket"
        elif stat.S_ISDIR(st.st_mode):
            kind = "dir"
        elif stat.S_ISREG(st.st_mode):
            kind = "file"
        else:
            kind = "other"
        entries.append({"path": path, "kind": kind, "size": st.st_size})
    return entries


def list_wandb_temp_dirs(temp_root: Path) -> list[str]:
    """Return paths of wandb-* directories directly under temp_root."""
    return [
        entry["path"]
        for entry in list_wandb_temp_entries(temp_root)
        if entry["kind"] == "dir"
    ]


def assert_no_new_wandb_entries(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    kinds: set[str] | None = None,
) -> None:
    """Assert after has no wandb temp entries that were not in before."""
    before_paths = {entry["path"] for entry in before}
    new_items = [entry for entry in after if entry["path"] not in before_paths]
    if kinds is not None:
        new_items = [entry for entry in new_items if entry["kind"] in kinds]
    assert not new_items, (
        f"New wandb temp entries detected: {[entry['path'] for entry in new_items]}"
    )


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
