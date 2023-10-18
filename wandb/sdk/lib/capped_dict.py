import collections
from typing import Any, Optional


class CappedDict(collections.OrderedDict):
    default_max_size = 50

    def __init__(self, max_size: Optional[int] = None) -> None:
        self.max_size = max_size or self.default_max_size
        super().__init__()

    def __setitem__(self, key: str, val: Any) -> None:
        if key not in self:
            max_size = self.max_size - 1
            self._prune_dict(max_size)
        super().__setitem__(key, val)

    def update(self, **kwargs: Any) -> None:  # type: ignore[override]
        super().update(**kwargs)
        self._prune_dict(self.max_size)

    def _prune_dict(self, max_size: int) -> None:
        if len(self) >= max_size:
            diff = len(self) - max_size
            for k in list(self.keys())[:diff]:
                del self[k]
