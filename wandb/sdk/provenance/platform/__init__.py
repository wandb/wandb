from __future__ import annotations

import os
from typing import Any


def enrich(emitter: Any, sys_root: str = "/sys") -> None:
    """Emit one Level 1 enrichment capability when DMI evidence names only AWS or OCI."""
    found = set()
    if os.environ.get("WANDB_X_PROVENANCE_PROVIDER") == "coreweave":
        found.add("coreweave")
    for name in ("sys_vendor", "product_name", "chassis_asset_tag"):
        try:
            with open(os.path.join(sys_root, "class/dmi/id", name)) as file:
                value = file.read(256).strip()
        except OSError:
            continue
        if name != "chassis_asset_tag" and "Google" in value:
            found.add("gcp")
        if name == "sys_vendor" and value == "Amazon EC2":
            found.add("aws")
        if name == "chassis_asset_tag" and value == "OracleCloud.com":
            found.add("oci")
    if found == {"aws"}:
        from .aws import collect
    elif found == {"oci"}:
        from .oci import collect
    else:
        return
    try:
        emitter.emit("capability", collect())
    except Exception:
        pass
