# """W&B callback for CatBoost

# Really simple callback to get logging for each tree

# Example usage:
"""
W&B callback for CatBoost
"""

from .catboost import log_summary, WandbCallback

__all__ = ["log_summary", "WandbCallback"]
