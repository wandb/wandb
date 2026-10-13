from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

SUPPORTED_COMMIT = "6b3b7d4"


def revision(modules) -> str | None:
    package = modules.get("torchtitan")
    if package is None:
        return None
    try:
        root = Path(package.__file__).resolve().parent.parent
        head = (root / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: refs/"):
            head = (root / ".git" / head.removeprefix("ref: ")).read_text().strip()
        if len(head) == 40 and all(char in "0123456789abcdef" for char in head):
            return head
    except (AttributeError, OSError, TypeError):
        pass
    try:
        direct = metadata.distribution("torchtitan").read_text("direct_url.json")
        return json.loads(direct or "{}").get("vcs_info", {}).get("commit_id")
    except (metadata.PackageNotFoundError, ValueError, TypeError):
        return None
