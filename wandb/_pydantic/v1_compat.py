"""Provides partial support for compatibility with Pydantic v1."""

from __future__ import annotations

import json
from functools import lru_cache
from inspect import signature
from operator import attrgetter
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal, overload

import pydantic

from .utils import IS_PYDANTIC_V2, to_json

if TYPE_CHECKING:
    from typing import Protocol

    class V1Model(Protocol):
        # ------------------------------------------------------------------------------
        # NOTE: These aren't part of the original v1 BaseModel spec, but were added as
        # internal helpers and are (re-)declared here to satisfy mypy checks.
        @classmethod
        def _dump_json_vals(cls, values: dict, by_alias: bool) -> dict: ...

        # ------------------------------------------------------------------------------
        # These methods are part of the original v1 BaseModel spec.

        __config__: ClassVar[type]
        __fields__: ClassVar[dict[str, Any]]
        __fields_set__: set[str]

        @classmethod
        def update_forward_refs(cls, *args: Any, **kwargs: Any) -> None: ...
        @classmethod
        def construct(cls, *args: Any, **kwargs: Any) -> V1Model: ...
        @classmethod
        def parse_obj(cls, *args: Any, **kwargs: Any) -> V1Model: ...
        @classmethod
        def parse_raw(cls, *args: Any, **kwargs: Any) -> V1Model: ...

        def dict(self, **kwargs: Any) -> dict[str, Any]: ...
        def json(self, **kwargs: Any) -> str: ...
        def copy(self, **kwargs: Any) -> V1Model: ...


# Maps {v2 -> v1} model config keys that were renamed in v2.
# See: https://docs.pydantic.dev/latest/migration/#changes-to-config
_V1_CONFIG_KEYS = {
    "populate_by_name": "allow_population_by_field_name",
    "str_to_lower": "anystr_lower",
    "str_strip_whitespace": "anystr_strip_whitespace",
    "str_to_upper": "anystr_upper",
    "ignored_types": "keep_untouched",
    "str_max_length": "max_anystr_length",
    "str_min_length": "min_anystr_length",
    "from_attributes": "orm_mode",
    "json_schema_extra": "schema_extra",
    "validate_default": "validate_all",
}


def convert_v2_config(v2_config: dict[str, Any]) -> dict[str, Any]:
    """Internal helper: Return a copy of the v2 ConfigDict with renamed v1 keys."""
    return {
        # Convert v2 config keys to v1 keys
        **{_V1_CONFIG_KEYS.get(k, k): v for k, v in v2_config.items()},
        # This is a v1-only config key. In v2, it no longer exists and is effectively always True.
        "underscore_attrs_are_private": True,
    }


@lru_cache(maxsize=None)  # Reduce repeat introspection via `signature()`
def allowed_arg_names(func: Callable) -> set[str]:
    """Internal helper: Return the names of args accepted by the given function."""
    return set(signature(func).parameters)


# Pydantic BaseModels are defined with a custom metaclass, but its namespace
# has changed between pydantic versions.
#
# In v1, it can be imported as `from pydantic.main import ModelMetaclass`
# In v2, it's defined in an internal module so we avoid directly importing it.
PydanticModelMetaclass: type = type(pydantic.BaseModel)


class V1MixinMetaclass(PydanticModelMetaclass):
    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ):
        # In the class definition, convert the model config, if any:
        #     class MyModel(BaseModel):  # BEFORE (v2)
        #         model_config = ConfigDict(populate_by_name=True)
        #
        #     class MyModel(BaseModel):  # AFTER (v1)
        #         class Config:
        #             allow_population_by_field_name = True
        if config_dict := namespace.pop("model_config", None):
            namespace["Config"] = type("Config", (), convert_v2_config(config_dict))
        return super().__new__(cls, name, bases, namespace, **kwargs)

    @property
    def model_fields(self) -> dict[str, Any]:
        return self.__fields__  # type: ignore[deprecated]


# Mixin to ensure compatibility of Pydantic models if Pydantic v1 is detected.
# These are "best effort" implementations and cannot guarantee complete
# compatibility in v1 environments.
#
# Whenever possible, users should strongly prefer upgrading to Pydantic v2 to
# ensure full compatibility.
class V1Mixin(metaclass=V1MixinMetaclass):
    # Internal compat helpers
    @classmethod
    def _dump_json_vals(cls, values: dict[str, Any], by_alias: bool) -> dict[str, Any]:
        """Reserialize values from `Json`-typed fields after dumping the model to dict."""
        # Get the expected keys (after `.model_dump()`) for `Json`-typed fields.
        # Note: In v1, `Json` fields have `ModelField.parse_json == True`
        json_fields = (f for f in cls.__fields__.values() if f.parse_json)  # type: ignore[deprecated]
        get_key = attrgetter("alias" if by_alias else "name")
        json_field_keys = set(map(get_key, json_fields))

        return {
            # Only serialize `Json` fields with non-null values.
            k: to_json(v) if ((v is not None) and (k in json_field_keys)) else v
            for k, v in values.items()
        }

    # ------------------------------------------------------------------------------
    @classmethod
    def __try_update_forward_refs__(cls: type[V1Model], **localns: Any) -> None:
        if hasattr(sup := super(), "__try_update_forward_refs__"):
            sup.__try_update_forward_refs__(**localns)

    @classmethod
    def model_rebuild(cls, *args: Any, **kwargs: Any) -> None:
        return cls.update_forward_refs(*args, **kwargs)

    @classmethod
    def model_construct(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.construct(*args, **kwargs)

    @classmethod
    def model_validate(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.parse_obj(*args, **kwargs)

    @classmethod
    def model_validate_json(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.parse_raw(*args, **kwargs)

    def model_dump(self: V1Model, **kwargs: Any) -> dict[str, Any]:
        # Pass only kwargs that are allowed in the V1 method.
        allowed_keys = allowed_arg_names(self.dict) & kwargs.keys()
        dict_ = self.dict(**{k: kwargs[k] for k in allowed_keys})

        # Ugly hack: Try to serialize `Json` fields correctly when `round_trip=True` in pydantic v1
        if kwargs.get("round_trip", False):
            by_alias: bool = kwargs.get("by_alias", False)
            return self._dump_json_vals(dict_, by_alias=by_alias)

        return dict_

    def model_dump_json(self: V1Model, **kwargs: Any) -> str:
        # Pass only kwargs that are allowed in the V1 method.
        allowed_keys = allowed_arg_names(self.json) & kwargs.keys()
        json_ = self.json(**{k: kwargs[k] for k in allowed_keys})

        # Ugly hack: Try to serialize `Json` fields correctly when `round_trip=True` in pydantic v1
        if kwargs.get("round_trip", False):
            by_alias: bool = kwargs.get("by_alias", False)
            dict_ = json.loads(json_)
            return json.dumps(self._dump_json_vals(dict_, by_alias=by_alias))

        return json_

    def model_copy(self: V1Model, **kwargs: Any) -> V1Model:
        # Pass only kwargs that are allowed in the V1 method.
        allowed_keys = allowed_arg_names(self.copy) & kwargs.keys()
        return self.copy(**{k: kwargs[k] for k in allowed_keys})

    @property
    def model_fields_set(self: V1Model) -> set[str]:
        return self.__fields_set__


# Placeholder. Pydantic v2 is already compatible with itself, so no need for extra mixins.
class V2Mixin:
    pass


# Pick the mixin type based on the detected Pydantic version.
PydanticCompatMixin: type = V2Mixin if IS_PYDANTIC_V2 else V1Mixin


# ----------------------------------------------------------------------------
# Decorators and other pydantic helpers
# ----------------------------------------------------------------------------
if IS_PYDANTIC_V2:
    from pydantic import alias_generators

    # https://docs.pydantic.dev/latest/api/config/#pydantic.alias_generators.to_camel
    to_camel = alias_generators.to_camel  # e.g. "foo_bar" -> "fooBar"

    # https://docs.pydantic.dev/latest/api/functional_validators/#pydantic.functional_validators.field_validator
    field_validator = pydantic.field_validator

    # https://docs.pydantic.dev/latest/api/functional_validators/#pydantic.functional_validators.model_validator
    model_validator = pydantic.model_validator

    # https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.computed_field
    computed_field = pydantic.computed_field

    # https://docs.pydantic.dev/latest/api/aliases/#pydantic.aliases.AliasChoices
    AliasChoices = pydantic.AliasChoices

else:
    from pydantic.utils import to_lower_camel

    V2ValidatorMode = Literal["before", "after", "wrap", "plain"]

    # NOTE:
    # - `to_lower_camel` in v1 is the equivalent of `to_camel` in v2 (i.e. to lowerCamelCase)
    # - `to_camel` in v1 is the equivalent of `to_pascal` in v2 (i.e. to UpperCamelCase)
    to_camel = to_lower_camel

    # Lets us use `@field_validator` from v2, while calling `@validator` from v1 if needed.
    def field_validator(
        *fields: str,
        mode: V2ValidatorMode = "after",
        check_fields: bool | None = None,
        **_: Any,
    ) -> Callable:
        return pydantic.validator(  # type: ignore[deprecated]
            *fields,
            pre=(mode == "before"),
            always=True,
            check_fields=bool(check_fields),
            allow_reuse=True,
        )

    # Lets us use `@model_validator` from v2, while calling `@root_validator` from v1 if needed.
    def model_validator(*, mode: V2ValidatorMode, **_: Any) -> Callable:
        if mode == "after":

            def _decorator(v2_method: Callable) -> Any:
                # Patch the behavior for `@model_validator(mode="after")` in v1.
                #
                # This is necessarily complicated because:
                # - `@model_validator(mode="after")` always decorates an instance method in v2,
                #   i.e. the decorated function has `self` as the first arg.
                # - `@root_validator(pre=False)` always decorates a classmethod in v1,
                #   i.e. the decorated function has `cls` as the first arg.

                def v1_method(
                    cls: type[V1Model], values: dict[str, Any]
                ) -> dict[str, Any]:
                    # values should already be validated in an "after" validator, so use `construct()`
                    # to instantiate without (re-)validating.
                    v_self = v2_method(cls.construct(**values))

                    # Pydantic v1 expects the validator to return a dict of {field_name -> value}
                    return {f: getattr(v_self, f) for f in v_self.__fields__}

                return pydantic.root_validator(pre=False, allow_reuse=True)(  # type: ignore[call-overload]
                    classmethod(v1_method)
                )

            return _decorator
        else:
            return pydantic.root_validator(pre=(mode == "before"), allow_reuse=True)  # type: ignore[call-overload]

    @overload  # type: ignore[no-redef]
    def computed_field(func: Callable | property, /) -> property: ...
    @overload
    def computed_field(
        func: None, /, **_: Any
    ) -> Callable[[Callable | property], property]: ...

    def computed_field(
        func: Callable | property | None = None, /, **_: Any
    ) -> property | Callable[[Callable | property], property]:
        """Compatibility wrapper for Pydantic v2's `computed_field` in v1."""

        def always_property(f: Callable | property) -> property:
            # Convert the method to a property only if needed
            return f if isinstance(f, property) else property(f)

        # Handle both decorator styles
        return always_property if (func is None) else always_property(func)

    class AliasChoices:  # type: ignore [no-redef]
        """Placeholder class for Pydantic v2's AliasChoices for partial v1 compatibility."""

        aliases: list[str]

        def __init__(self, *aliases: str):
            self.aliases = list(aliases)
