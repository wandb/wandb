from functools import wraps
import os
from typing import Any, Callable, cast, TypeVar

FuncT = TypeVar("FuncT", bound=Callable[..., Any])

requirement_env_var_mapping = {"report-editing:v0": "WANDB_REQUIRE_REPORT_EDITING_V0"}


def requires(requirement: str) -> FuncT:
    """
    The decorator for gating features.
    """
    env_var = requirement_env_var_mapping[requirement]

    def deco(func: FuncT) -> FuncT:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not os.getenv(env_var):
                raise Exception(
                    f'You need to enable this feature with `wandb.require("{requirement}")`'
                )
            return func(*args, **kwargs)

        return cast(FuncT, wrapper)

    return cast(FuncT, deco)


class RequiresMixin:
    requirement = ""

    def __init__(self) -> None:
        """
        This hook for normal classes
        """
        self._check_if_requirements_met()

    def __post_init__(self) -> None:
        """
        This hook added for dataclasses
        """
        self._check_if_requirements_met()

    def _check_if_requirements_met(self) -> None:
        env_var = requirement_env_var_mapping[self.requirement]
        if not os.getenv(env_var):
            raise Exception(
                f'You must explicitly enable this feature with `wandb.require("{self.requirement})"'
            )


class RequiresReportEditingMixin(RequiresMixin):
    requirement = "report-editing:v0"
