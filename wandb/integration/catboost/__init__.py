"""
W&B callback for CatBoost
"""

from .catboost import log_summary, WandbCallback

__all__ = ["log_summary", "WandbCallback"]
