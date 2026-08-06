from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from cwsandbox import NetworkOptions, RemoteFunction, ResourceOptions, SandboxDefaults
from cwsandbox import Sandbox as _BaseSandbox
from cwsandbox import Session as _BaseSession

from wandb.errors import UsageError

_PLACEMENT_OVERRIDE_FIELDS = ("profile_ids", "profile_names", "runner_ids")
_SUPPORTED_EGRESS_MODES = ("internet", "none")
_SERVERLESS_DEFAULT_MAX_LIFETIME_SECONDS = 12 * 60 * 60
P = ParamSpec("P")
R = TypeVar("R")


def _placement_override_error(fields: Sequence[str]) -> UsageError:
    fields_display = ", ".join(fields)
    return UsageError(
        "W&B Serverless automatically selects the runner and profile. "
        f"Remove ({fields_display})."
    )


def _reject_placement_override_kwargs(kwargs: Mapping[str, Any]) -> None:
    blocked = [
        field
        for field in _PLACEMENT_OVERRIDE_FIELDS
        if field in kwargs and kwargs[field] is not None
    ]
    if blocked:
        raise _placement_override_error(blocked)


def _resources_include_gpu(
    resources: ResourceOptions | Mapping[str, Any] | None,
) -> bool:
    if resources is None:
        return False

    if isinstance(resources, Mapping):
        gpu = resources.get("gpu")
        return gpu is not None and gpu != {}

    if isinstance(resources, ResourceOptions):
        return resources.gpu is not None

    return False


def _reject_gpu_resources(
    resources: ResourceOptions | Mapping[str, Any] | None,
) -> None:
    if _resources_include_gpu(resources):
        raise UsageError(
            "W&B Serverless currently supports only CPU and memory resources. "
            "Remove resources.gpu."
        )


def _reject_unsupported_egress_mode(
    network: NetworkOptions | Mapping[str, Any] | None,
) -> None:
    if network is None:
        return

    if isinstance(network, Mapping):
        egress_mode = network.get("egress_mode")
    elif isinstance(network, NetworkOptions):
        egress_mode = network.egress_mode
    else:
        return

    if egress_mode is not None and egress_mode not in _SUPPORTED_EGRESS_MODES:
        modes_display = ", ".join(_SUPPORTED_EGRESS_MODES)
        raise UsageError(
            "wandb.sandbox supports only egress modes "
            f"({modes_display}). Got {egress_mode!r}."
        )


def _reject_invalid_kwargs(kwargs: Mapping[str, Any]) -> None:
    _reject_placement_override_kwargs(kwargs)
    _reject_gpu_resources(kwargs.get("resources"))
    _reject_unsupported_egress_mode(kwargs.get("network"))


def _with_serverless_max_lifetime_default(
    defaults: SandboxDefaults | Mapping[str, Any] | None,
) -> SandboxDefaults:
    if defaults is None:
        return SandboxDefaults(
            max_lifetime_seconds=_SERVERLESS_DEFAULT_MAX_LIFETIME_SECONDS
        )

    if isinstance(defaults, Mapping):
        coerced = SandboxDefaults.from_dict(defaults)
        if coerced.max_lifetime_seconds is not None:
            return coerced
        return coerced.with_overrides(
            max_lifetime_seconds=_SERVERLESS_DEFAULT_MAX_LIFETIME_SECONDS
        )

    if defaults.max_lifetime_seconds is not None:
        return defaults

    return defaults.with_overrides(
        max_lifetime_seconds=_SERVERLESS_DEFAULT_MAX_LIFETIME_SECONDS
    )


def _apply_serverless_defaults_kwargs(kwargs: dict[str, Any]) -> None:
    if kwargs.get("max_lifetime_seconds") is not None:
        return
    kwargs["defaults"] = _with_serverless_max_lifetime_default(kwargs.get("defaults"))


def _reject_invalid_defaults(
    defaults: SandboxDefaults | Mapping[str, Any] | None,
) -> None:
    if defaults is None:
        return

    if isinstance(defaults, Mapping):
        blocked = [
            field
            for field in _PLACEMENT_OVERRIDE_FIELDS
            if field in defaults and defaults[field] is not None
        ]
    else:
        blocked = [
            field
            for field in _PLACEMENT_OVERRIDE_FIELDS
            if getattr(defaults, field, None) is not None
        ]

    if blocked:
        raise _placement_override_error(blocked)

    resources = (
        defaults.get("resources")
        if isinstance(defaults, Mapping)
        else getattr(defaults, "resources", None)
    )
    _reject_gpu_resources(resources)

    network = (
        defaults.get("network")
        if isinstance(defaults, Mapping)
        else getattr(defaults, "network", None)
    )
    _reject_unsupported_egress_mode(network)


class Sandbox(_BaseSandbox):
    """W&B sandbox wrapper with W&B Serverless policy guardrails."""

    if TYPE_CHECKING:
        __init__ = _BaseSandbox.__init__
    else:

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _reject_invalid_kwargs(kwargs)
            _reject_invalid_defaults(kwargs.get("defaults"))
            _apply_serverless_defaults_kwargs(kwargs)
            super().__init__(*args, **kwargs)

    @classmethod
    def session(cls, *args: Any, **kwargs: Any) -> Session:
        return Session(*args, **kwargs)


class Session(_BaseSession):
    """W&B sandbox session wrapper with W&B Serverless policy guardrails."""

    if TYPE_CHECKING:
        __init__ = _BaseSession.__init__
        sandbox = _BaseSession.sandbox
        function = _BaseSession.function
    else:

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            if args:
                _reject_invalid_defaults(args[0])
                args = (_with_serverless_max_lifetime_default(args[0]), *args[1:])
            else:
                _reject_invalid_defaults(kwargs.get("defaults"))
                _apply_serverless_defaults_kwargs(kwargs)
            super().__init__(*args, **kwargs)

        def sandbox(
            self,
            **kwargs: Any,
        ) -> _BaseSandbox:
            _reject_invalid_kwargs(kwargs)
            return super().sandbox(**kwargs)

        def function(
            self,
            **kwargs: Any,
        ) -> Callable[[Callable[P, R]], RemoteFunction[P, R]]:
            _reject_invalid_kwargs(kwargs)
            return super().function(**kwargs)
