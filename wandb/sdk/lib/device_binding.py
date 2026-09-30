"""Reports the CUDA device the current process is bound to."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

_RECHECK_SECONDS = 60.0


class DeviceBindingReporter:
    """Publishes torch's current CUDA device; call on the CUDA thread."""

    def __init__(
        self,
        publish: Callable[[str, str, int], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._publish = publish
        self._clock = clock
        self._disabled = False
        self._uuid: str | None = None
        self._last_check = 0.0

    def maybe_report(self) -> None:
        if self._disabled:
            return
        elapsed = self._clock() - self._last_check
        if self._uuid is not None and elapsed < _RECHECK_SECONDS:
            return

        # Never import torch or initialize CUDA on the user's behalf.
        torch = sys.modules.get("torch")
        if torch is None:
            return

        try:
            if not torch.cuda.is_initialized():
                return
            self._last_check = self._clock()
            index = torch.cuda.current_device()
            props = torch.cuda.get_device_properties(index)
            uuid = str(props.uuid).strip()
            if not uuid.upper().startswith("GPU-"):
                uuid = f"GPU-{uuid}"
            if uuid == self._uuid:
                return

            domain = getattr(props, "pci_domain_id", None)
            bus = getattr(props, "pci_bus_id", None)
            device = getattr(props, "pci_device_id", None)
            pci_bus_id = (
                f"{domain:08X}:{bus:02X}:{device:02X}.0"
                if None not in (domain, bus, device)
                else ""
            )

            self._publish(uuid, pci_bus_id, index)
            self._uuid = uuid
        except Exception:
            self._disabled = True
