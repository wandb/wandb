import os
from functools import wraps
from typing import Any, Callable, Dict, TypeVar, cast

FuncT = TypeVar("FuncT", bound=Callable[..., Any])

requirement_env_var_mapping: Dict[str, str] = {
    "report-editing:v0": "WANDB_REQUIRE_REPORT_EDITING_V0"
}


def requires(requirement: str) -> FuncT:  # type: ignore
    """Decorate functions to gate features with wandb.require."""
    env_var = requirement_env_var_mapping[requirement]

    def deco(func: FuncT) -> FuncT:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not os.getenv(env_var):
                raise Exception(
                    f"You need to enable this feature with `wandb.require({requirement!r})`"
                )
            return func(*args, **kwargs)

        return cast(FuncT, wrapper)

    return cast(FuncT, deco)


class RequiresMixin:
    requirement = ""

    def __init__(self) -> None:
        self._check_if_requirements_met()

    def __post_init__(self) -> None:
        self._check_if_requirements_met()

    def _check_if_requirements_met(self) -> None:
        env_var = requirement_env_var_mapping[self.requirement]
        if not os.getenv(env_var):
            raise Exception(
                f'You must explicitly enable this feature with `wandb.require("{self.requirement})"'
            )
