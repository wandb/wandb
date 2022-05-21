from functools import wraps
import os

requirement_env_var_mapping = {"report-editing:v0": "WANDB_REQUIRE_REPORT_EDITING_V0"}


def requires(requirement):
    """
    The decorator for gating features.
    """
    env_var = requirement_env_var_mapping[requirement]

    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not os.getenv(env_var):
                raise Exception(
                    f'You need to enable this feature with `wandb.require("{requirement}")`'
                )
            return func(*args, **kwargs)

        return wrapper

    return deco


class RequiresMixin:
    requirement = None

    def __post_init__(self):
        env_var = requirement_env_var_mapping[self.requirement]
        if not os.getenv(env_var):
            raise Exception(
                f'You must explicitly enable this feature with `wandb.require("{self.requirement})"'
            )


class RequiresReportEditingMixin(RequiresMixin):
    requirement = "report-editing:v0"
