import datetime
import math
import typing as t

from wandb.util import (
    _is_artifact_string,
    _is_artifact_version_weave_dict,
    get_module,
    is_numpy_array,
)

np = get_module("numpy")  # intentionally not required

if t.TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

ConvertibleToType = t.Union["Type", t.Type["Type"], type, t.Any]


class TypeRegistry:
    """A resolver for python objects that can deserialize JSON dicts.

    Additional types can be registered via the .add call.
    """

    _types_by_name = None
    _types_by_class = None

    @staticmethod
    def types_by_name():
        if TypeRegistry._types_by_name is None:
            TypeRegistry._types_by_name = {}
        return TypeRegistry._types_by_name

    @staticmethod
    def types_by_class():
        if TypeRegistry._types_by_class is None:
            TypeRegistry._types_by_class = {}
        return TypeRegistry._types_by_class

    @staticmethod
    def add(wb_type: t.Type["Type"]) -> None:
        assert issubclass(wb_type, Type)
        TypeRegistry.types_by_name().update({wb_type.name: wb_type})
        for name in wb_type.legacy_names:
            TypeRegistry.types_by_name().update({name: wb_type})
        TypeRegistry.types_by_class().update(
            {_type: wb_type for _type in wb_type.types}
        )

    @staticmethod
    def type_of(py_obj: t.Optional[t.Any]) -> "Type":
        # Special case handler for common case of np.nans. np.nan
        # is of type 'float', but should be treated as a None. This is
        # because np.nan can co-exist with other types in dataframes,
        # but will be ultimately treated as a None. Ignoring type since
        # mypy does not trust that py_obj is a float by the time it is
        # passed to isnan.
        if py_obj.__class__ is float and math.isnan(py_obj):  # type: ignore
            return NoneType()

        # TODO: generalize this to handle other config input types
        if _is_artifact_string(py_obj) or _is_artifact_version_weave_dict(py_obj):
            return TypeRegistry.types_by_name().get("artifactVersion")()

        class_handler = TypeRegistry.types_by_class().get(py_obj.__class__)
        _type = None
        if class_handler:
            _type = class_handler.from_obj(py_obj)
        else:
            _type = PythonObjectType.from_obj(py_obj)
        return _type

    @staticmethod
    def type_from_dict(
        json_dict: t.Dict[str, t.Any], artifact: t.Optional["Artifact"] = None
    ) -> "Type":
        wb_type = json_dict.get("wb_type")
        if wb_type is None:
            TypeError("json_dict must contain `wb_type` key")
        _type = TypeRegistry.types_by_name().get(wb_type)
        if _type is None:
            TypeError(f"missing type handler for {wb_type}")
        return _type.from_json(json_dict, artifact)

    @staticmethod
    def type_from_dtype(dtype: ConvertibleToType) -> "Type":
        # The dtype is already an instance of Type
        if isinstance(dtype, Type):
            wbtype: Type = dtype

        # The dtype is a subclass of Type
        elif isinstance(dtype, type) and issubclass(dtype, Type):
            wbtype = dtype()

        # The dtype is a subclass of generic python type
        elif isinstance(dtype, type):
            handler = TypeRegistry.types_by_class().get(dtype)

            # and we have a registered handler
            if handler:
                wbtype = handler()

            # else, fallback to object type
            else:
                wbtype = PythonObjectType.from_obj(dtype)

        # The dtype is a list, then we resolve the list notation
        elif isinstance(dtype, list):
            if len(dtype) == 0:
                wbtype = ListType()
            elif len(dtype) == 1:
                wbtype = ListType(TypeRegistry.type_from_dtype(dtype[0]))

            # lists of more than 1 are treated as unions
            else:
                wbtype = UnionType([TypeRegistry.type_from_dtype(dt) for dt in dtype])

        # The dtype is a dict, then we resolve the dict notation
        elif isinstance(dtype, dict):
            wbtype = TypedDictType(
                {key: TypeRegistry.type_from_dtype(dtype[key]) for key in dtype}
            )

        # The dtype is a concrete instance, which we will treat as a constant
        else:
            wbtype = ConstType(dtype)

        return wbtype


def _params_obj_to_json_obj(
    params_obj: t.Any,
    artifact: t.Optional["Artifact"] = None,
) -> t.Any:
    """Helper method."""
    if params_obj.__class__ is dict:
        return {
            key: _params_obj_to_json_obj(params_obj[key], artifact)
            for key in params_obj
        }
    elif params_obj.__class__ in [list, set, tuple, frozenset]:
        return [_params_obj_to_json_obj(item, artifact) for item in list(params_obj)]
    elif isinstance(params_obj, Type):
        return params_obj.to_json(artifact)
    else:
        return params_obj


def _json_obj_to_params_obj(
    json_obj: t.Any, artifact: t.Optional["Artifact"] = None
) -> t.Any:
    """Helper method."""
    if json_obj.__class__ is dict:
        if "wb_type" in json_obj:
            return TypeRegistry.type_from_dict(json_obj, artifact)
        else:
            return {
                key: _json_obj_to_params_obj(json_obj[key], artifact)
                for key in json_obj
            }
    elif json_obj.__class__ is list:
        return [_json_obj_to_params_obj(item, artifact) for item in json_obj]
    else:
        return json_obj


class Type:
    """The most generic type that all types subclass.

    It provides simple serialization and deserialization as well as equality checks.
    A name class-level property must be uniquely set by subclasses.
    """

    # Subclasses must override with a unique name. This is used to identify the
    # class during serializations and deserializations
    name: t.ClassVar[str] = ""

    # List of names by which this class can deserialize
    legacy_names: t.ClassVar[t.List[str]] = []

    # Subclasses may override with a list of `types` which this Type is capable
    # of being initialized. This is used by the Type Registry when calling `TypeRegistry.type_of`.
    # Some types will have an empty list - for example `Union`. There is no raw python type which
    # inherently maps to a Union and therefore the list should be empty.
    types: t.ClassVar[t.List[type]] = []

    # Contains the further specification of the Type
    _params: t.Dict[str, t.Any]

    def __init__(*args, **kwargs):
        pass

    @property
    def params(self):
        if not hasattr(self, "_params") or self._params is None:
            self._params = {}
        return self._params

    def assign(self, py_obj: t.Optional[t.Any] = None) -> "Type":
        """Assign a python object to the type.

        May to be overridden by subclasses

        Args:
            py_obj (any, optional): Any python object which the user wishes to assign to
            this type

        Returns:
            Type: a new type representing the result of the assignment.
        """
        return self.assign_type(TypeRegistry.type_of(py_obj))

    def assign_type(self, wb_type: "Type") -> "Type":
        # Default - should be overridden
        if isinstance(wb_type, self.__class__) and self.params == wb_type.params:
            return self
        else:
            return InvalidType()

    def to_json(self, artifact: t.Optional["Artifact"] = None) -> t.Dict[str, t.Any]:
        """Generate a jsonable dictionary serialization the type.

        If overridden by subclass, ensure that `from_json` is equivalently overridden.

        Args:
            artifact (wandb.Artifact, optional): If the serialization is being performed
            for a particular artifact, pass that artifact. Defaults to None.

        Returns:
            dict: Representation of the type
        """
        res = {
            "wb_type": self.name,
            "params": _params_obj_to_json_obj(self.params, artifact),
        }
        if res["params"] is None or res["params"] == {}:
            del res["params"]

        return res

    @classmethod
    def from_json(
        cls,
        json_dict: t.Dict[str, t.Any],
        artifact: t.Optional["Artifact"] = None,
    ) -> "Type":
        """Construct a new instance of the type using a JSON dictionary.

        The mirror function of `to_json`. If overridden by subclass, ensure that
        `to_json` is equivalently overridden.

        Returns:
            _Type: an instance of a subclass of the _Type class.
        """
        return cls(**_json_obj_to_params_obj(json_dict.get("params", {}), artifact))

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "Type":
        return cls()

    def explain(self, other: t.Any, depth=0) -> str:
        """Explain why an item is not assignable to a type.

        Assumes that the caller has already validated that the assignment fails.

        Args:
            other (any): Any object depth (int, optional): depth of the type checking.
                Defaults to 0.

        Returns:
            str: human-readable explanation
        """
        wbtype = TypeRegistry.type_of(other)
        gap = "".join(["\t"] * depth)
        if depth > 0:
            return f"{gap}{wbtype} not assignable to {self}"
        else:
            return f"{gap}{other} of type {wbtype} is not assignable to {self}"

    def __repr__(self):
        rep = self.name.capitalize()
        if len(self.params.keys()) > 0:
            rep += "("
            for ndx, key in enumerate(self.params.keys()):
                if ndx > 0:
                    rep += ", "
                rep += key + ":" + str(self.params[key])
            rep += ")"
        return rep

    def __eq__(self, other):
        return self is other or (
            isinstance(self, Type)
            and isinstance(other, Type)
            and self.name == other.name
            and self.params.keys() == other.params.keys()
            and all([self.params[k] == other.params[k] for k in self.params])
        )


class InvalidType(Type):
    """A disallowed type.

    Assignments to a InvalidType result in a Never Type. InvalidType is basically the
    invalid case.
    """

    name = "invalid"
    types: t.ClassVar[t.List[type]] = []

    def assign_type(self, wb_type: "Type") -> "InvalidType":
        return self


class AnyType(Type):
    """An object that can be any type.

    Assignments to an AnyType result in the AnyType except None which results in an
    InvalidType.
    """

    name = "any"
    types: t.ClassVar[t.List[type]] = []

    def assign_type(self, wb_type: "Type") -> t.Union["AnyType", InvalidType]:
        return (
            self
            if not (isinstance(wb_type, NoneType) or isinstance(wb_type, InvalidType))
            else InvalidType()
        )


class UnknownType(Type):
    """An object with an unknown type.

    All assignments to an UnknownType result in the type of the assigned object except
    `None` which results in a InvalidType.
    """

    name = "unknown"
    types: t.ClassVar[t.List[type]] = []

    def assign_type(self, wb_type: "Type") -> "Type":
        return wb_type if not isinstance(wb_type, NoneType) else InvalidType()


class NoneType(Type):
    name = "none"
    types: t.ClassVar[t.List[type]] = [None.__class__]


class StringType(Type):
    name = "string"
    types: t.ClassVar[t.List[type]] = [str]


class NumberType(Type):
    name = "number"
    types: t.ClassVar[t.List[type]] = [int, float]


if np:
    NumberType.types.append(np.byte)
    NumberType.types.append(np.short)
    NumberType.types.append(np.ushort)
    NumberType.types.append(np.intc)
    NumberType.types.append(np.uintc)
    NumberType.types.append(np.int_)
    NumberType.types.append(np.uint)
    NumberType.types.append(np.longlong)
    NumberType.types.append(np.ulonglong)
    NumberType.types.append(np.half)
    NumberType.types.append(np.float16)
    NumberType.types.append(np.single)
    NumberType.types.append(np.double)
    NumberType.types.append(np.longdouble)
    NumberType.types.append(np.csingle)
    NumberType.types.append(np.cdouble)
    NumberType.types.append(np.clongdouble)
    NumberType.types.append(np.int8)
    NumberType.types.append(np.int16)
    NumberType.types.append(np.int32)
    NumberType.types.append(np.int64)
    NumberType.types.append(np.uint8)
    NumberType.types.append(np.uint16)
    NumberType.types.append(np.uint32)
    NumberType.types.append(np.uint64)
    NumberType.types.append(np.intp)
    NumberType.types.append(np.uintp)
    NumberType.types.append(np.float32)
    NumberType.types.append(np.float64)
    NumberType.types.append(np.complex64)
    NumberType.types.append(np.complex128)

    numpy_major_version = np.__version__.split(".")[0]
    if int(numpy_major_version) < 2:
        NumberType.types.append(np.float_)
        NumberType.types.append(np.complex_)


class TimestampType(Type):
    name = "timestamp"
    types: t.ClassVar[t.List[type]] = [datetime.datetime, datetime.date]


if np:
    TimestampType.types.append(np.datetime64)


class BooleanType(Type):
    name = "boolean"
    types: t.ClassVar[t.List[type]] = [bool]


if np:
    BooleanType.types.append(np.bool_)


class PythonObjectType(Type):
    """A backup type that keeps track of the python object name."""

    name = "pythonObject"
    legacy_names = ["object"]
    types: t.ClassVar[t.List[type]] = []

    def __init__(self, class_name: str):
        self.params.update({"class_name": class_name})

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "PythonObjectType":
        return cls(py_obj.__class__.__name__)


class ConstType(Type):
    """A constant value (currently only primitives supported)."""

    name = "const"
    types: t.ClassVar[t.List[type]] = []

    def __init__(self, val: t.Optional[t.Any] = None, is_set: t.Optional[bool] = False):
        if val.__class__ not in [str, int, float, bool, set, list, None.__class__]:
            TypeError(
                f"ConstType only supports str, int, float, bool, set, list, and None types. Found {val}"
            )
        if is_set or isinstance(val, set):
            is_set = True
            assert isinstance(val, set) or isinstance(val, list)
            val = set(val)

        self.params.update({"val": val, "is_set": is_set})

    def assign(self, py_obj: t.Optional[t.Any] = None) -> "Type":
        return self.assign_type(ConstType(py_obj))

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "ConstType":
        return cls(py_obj)

    def __repr__(self):
        return str(self.params["val"])


def _flatten_union_types(wb_types: t.List[Type]) -> t.List[Type]:
    final_types = []
    for allowed_type in wb_types:
        if isinstance(allowed_type, UnionType):
            internal_types = _flatten_union_types(allowed_type.params["allowed_types"])
            for internal_type in internal_types:
                final_types.append(internal_type)
        else:
            final_types.append(allowed_type)
    return final_types


def _union_assigner(
    allowed_types: t.List[Type],
    obj_or_type: t.Union[Type, t.Optional[t.Any]],
    type_mode=False,
) -> t.Union[t.List[Type], InvalidType]:
    resolved_types = []
    valid = False
    unknown_count = 0

    for allowed_type in allowed_types:
        if valid:
            resolved_types.append(allowed_type)
        else:
            if isinstance(allowed_type, UnknownType):
                unknown_count += 1
            else:
                if type_mode:
                    assert isinstance(obj_or_type, Type)
                    assigned_type = allowed_type.assign_type(obj_or_type)
                else:
                    assigned_type = allowed_type.assign(obj_or_type)
                if isinstance(assigned_type, InvalidType):
                    resolved_types.append(allowed_type)
                else:
                    resolved_types.append(assigned_type)
                    valid = True

    if not valid:
        if unknown_count == 0:
            return InvalidType()
        else:
            if type_mode:
                assert isinstance(obj_or_type, Type)
                new_type = obj_or_type
            else:
                new_type = UnknownType().assign(obj_or_type)
            if isinstance(new_type, InvalidType):
                return InvalidType()
            else:
                resolved_types.append(new_type)
                unknown_count -= 1

    for _ in range(unknown_count):
        resolved_types.append(UnknownType())

    resolved_types = _flatten_union_types(resolved_types)
    resolved_types.sort(key=str)
    return resolved_types


class UnionType(Type):
    """An "or" of types."""

    name = "union"
    types: t.ClassVar[t.List[type]] = []

    def __init__(
        self,
        allowed_types: t.Optional[t.Sequence[ConvertibleToType]] = None,
    ):
        assert allowed_types is None or (allowed_types.__class__ is list)
        if allowed_types is None:
            wb_types = []
        else:
            wb_types = [TypeRegistry.type_from_dtype(dt) for dt in allowed_types]

        wb_types = _flatten_union_types(wb_types)
        wb_types.sort(key=str)
        self.params.update({"allowed_types": wb_types})

    def assign(
        self, py_obj: t.Optional[t.Any] = None
    ) -> t.Union["UnionType", InvalidType]:
        resolved_types = _union_assigner(
            self.params["allowed_types"], py_obj, type_mode=False
        )
        if isinstance(resolved_types, InvalidType):
            return InvalidType()
        return self.__class__(resolved_types)

    def assign_type(self, wb_type: "Type") -> t.Union["UnionType", InvalidType]:
        if isinstance(wb_type, UnionType):
            assignees = wb_type.params["allowed_types"]
        else:
            assignees = [wb_type]

        resolved_types = self.params["allowed_types"]
        for assignee in assignees:
            resolved_types = _union_assigner(resolved_types, assignee, type_mode=True)
            if isinstance(resolved_types, InvalidType):
                return InvalidType()

        return self.__class__(resolved_types)

    def explain(self, other: t.Any, depth=0) -> str:
        exp = super().explain(other, depth)
        for ndx, subtype in enumerate(self.params["allowed_types"]):
            if ndx > 0:
                exp += "\n{}and".format("".join(["\t"] * depth))
            exp += "\n" + subtype.explain(other, depth=depth + 1)
        return exp

    def __repr__(self):
        return "{}".format(" or ".join([str(t) for t in self.params["allowed_types"]]))


def OptionalType(dtype: ConvertibleToType) -> UnionType:  # noqa: N802
    """Function that mimics the Type class API for constructing an "Optional Type".

    This is just a Union[wb_type, NoneType].

    Args:
        dtype (Type): type to be optional

    Returns:
        Type: Optional version of the type.
    """
    return UnionType([TypeRegistry.type_from_dtype(dtype), NoneType()])


class ListType(Type):
    """A list of homogeneous types."""

    name = "list"
    types: t.ClassVar[t.List[type]] = [list, tuple, set, frozenset]

    def __init__(
        self,
        element_type: t.Optional[ConvertibleToType] = None,
        length: t.Optional[int] = None,
    ):
        if element_type is None:
            wb_type: Type = UnknownType()
        else:
            wb_type = TypeRegistry.type_from_dtype(element_type)

        self.params.update({"element_type": wb_type, "length": length})

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "ListType":
        if py_obj is None or not hasattr(py_obj, "__iter__"):
            raise TypeError("ListType.from_obj expects py_obj to by list-like")
        else:
            if hasattr(py_obj, "tolist"):
                py_list = py_obj.tolist()
            else:
                py_list = list(py_obj)
            elm_type = (
                UnknownType() if None not in py_list else OptionalType(UnknownType())
            )
            for item in py_list:
                _elm_type = elm_type.assign(item)
                # Commenting this out since we don't want to crash user code at this point, but rather
                # retain an invalid internal list type.
                # if isinstance(_elm_type, InvalidType):
                #     raise TypeError(
                #         "List contained incompatible types. Item at index {}: \n{}".format(
                #             ndx, elm_type.explain(item, 1)
                #         )
                #     )

                elm_type = _elm_type

            return cls(elm_type, len(py_list))

    def assign_type(self, wb_type: "Type") -> t.Union["ListType", InvalidType]:
        if isinstance(wb_type, ListType):
            assigned_type = self.params["element_type"].assign_type(
                wb_type.params["element_type"]
            )
            if not isinstance(assigned_type, InvalidType):
                return ListType(
                    assigned_type,
                    None
                    if self.params["length"] != wb_type.params["length"]
                    else self.params["length"],
                )

        return InvalidType()

    def assign(
        self, py_obj: t.Optional[t.Any] = None
    ) -> t.Union["ListType", InvalidType]:
        if hasattr(py_obj, "__iter__"):
            new_element_type = self.params["element_type"]
            # The following ignore is needed since the above hasattr(py_obj, "__iter__") enforces iteration
            # error: Argument 1 to "list" has incompatible type "Optional[Any]"; expected "Iterable[Any]"
            py_list = list(py_obj)  # type: ignore
            for obj in py_list:
                new_element_type = new_element_type.assign(obj)
                if isinstance(new_element_type, InvalidType):
                    return InvalidType()
            return ListType(new_element_type, len(py_list))

        return InvalidType()

    def explain(self, other: t.Any, depth=0) -> str:
        exp = super().explain(other, depth)
        gap = "".join(["\t"] * depth)
        if (  # yes, this is a bit verbose, but the mypy typechecker likes it this way
            isinstance(other, list)
            or isinstance(other, tuple)
            or isinstance(other, set)
            or isinstance(other, frozenset)
        ):
            new_element_type = self.params["element_type"]
            for ndx, obj in enumerate(list(other)):
                _new_element_type = new_element_type.assign(obj)
                if isinstance(_new_element_type, InvalidType):
                    exp += "\n{}Index {}:\n{}".format(
                        gap, ndx, new_element_type.explain(obj, depth + 1)
                    )
                    break
                new_element_type = _new_element_type
        return exp

    def __repr__(self):
        return "{}[]".format(self.params["element_type"])


class NDArrayType(Type):
    """Represents a list of homogeneous types."""

    name = "ndarray"
    types: t.ClassVar[t.List[type]] = []  # will manually add type if np is available
    _serialization_path: t.Optional[t.Dict[str, str]]

    def __init__(
        self,
        shape: t.Sequence[int],
        serialization_path: t.Optional[t.Dict[str, str]] = None,
    ):
        self.params.update({"shape": list(shape)})
        self._serialization_path = serialization_path

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "NDArrayType":
        if is_numpy_array(py_obj):
            return cls(py_obj.shape)  # type: ignore
        elif isinstance(py_obj, list):
            shape = []
            target = py_obj
            while isinstance(target, list):
                dim = len(target)
                shape.append(dim)
                if dim > 0:
                    target = target[0]
            return cls(shape)
        else:
            raise TypeError(
                "NDArrayType.from_obj expects py_obj to be ndarray or list, found {}".format(
                    py_obj.__class__
                )
            )

    def assign_type(self, wb_type: "Type") -> t.Union["NDArrayType", InvalidType]:
        if (
            isinstance(wb_type, NDArrayType)
            and self.params["shape"] == wb_type.params["shape"]
        ):
            return self
        elif isinstance(wb_type, ListType):
            # Should we return error here?
            return self

        return InvalidType()

    def assign(
        self, py_obj: t.Optional[t.Any] = None
    ) -> t.Union["NDArrayType", InvalidType]:
        if is_numpy_array(py_obj) or isinstance(py_obj, list):
            py_type = self.from_obj(py_obj)
            return self.assign_type(py_type)

        return InvalidType()

    def to_json(self, artifact: t.Optional["Artifact"] = None) -> t.Dict[str, t.Any]:
        # custom override to support serialization path outside of params internal dict
        res = {
            "wb_type": self.name,
            "params": {
                "shape": self.params["shape"],
                "serialization_path": self._serialization_path,
            },
        }

        return res

    def _get_serialization_path(self) -> t.Optional[t.Dict[str, str]]:
        return self._serialization_path

    def _set_serialization_path(self, path: str, key: str) -> None:
        self._serialization_path = {"path": path, "key": key}

    def _clear_serialization_path(self) -> None:
        self._serialization_path = None


if np:
    NDArrayType.types.append(np.ndarray)

# class KeyPolicy:
#     EXACT = "E"  # require exact key match
#     SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
#     UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown


class TypedDictType(Type):
    """Represents a dictionary object where each key can have a type."""

    name = "typedDict"
    legacy_names = ["dictionary"]
    types: t.ClassVar[t.List[type]] = [dict]

    def __init__(
        self,
        type_map: t.Optional[t.Dict[str, ConvertibleToType]] = None,
    ):
        if type_map is None:
            type_map = {}
        self.params.update(
            {
                "type_map": {
                    key: TypeRegistry.type_from_dtype(type_map[key]) for key in type_map
                }
            }
        )

    @classmethod
    def from_obj(cls, py_obj: t.Optional[t.Any] = None) -> "TypedDictType":
        if not isinstance(py_obj, dict):
            TypeError("TypedDictType.from_obj expects a dictionary")

        assert isinstance(py_obj, dict)  # helps mypy type checker
        return cls({key: TypeRegistry.type_of(py_obj[key]) for key in py_obj})

    def assign_type(self, wb_type: "Type") -> t.Union["TypedDictType", InvalidType]:
        if (
            isinstance(wb_type, TypedDictType)
            and len(
                set(wb_type.params["type_map"].keys())
                - set(self.params["type_map"].keys())
            )
            == 0
        ):
            type_map = {}
            for key in self.params["type_map"]:
                type_map[key] = self.params["type_map"][key].assign_type(
                    wb_type.params["type_map"].get(key, UnknownType())
                )
                if isinstance(type_map[key], InvalidType):
                    return InvalidType()
            return TypedDictType(type_map)

        return InvalidType()

    def assign(
        self, py_obj: t.Optional[t.Any] = None
    ) -> t.Union["TypedDictType", InvalidType]:
        if (
            isinstance(py_obj, dict)
            and len(set(py_obj.keys()) - set(self.params["type_map"].keys())) == 0
        ):
            type_map = {}
            for key in self.params["type_map"]:
                type_map[key] = self.params["type_map"][key].assign(
                    py_obj.get(key, None)
                )
                if isinstance(type_map[key], InvalidType):
                    return InvalidType()
            return TypedDictType(type_map)

        return InvalidType()

    def explain(self, other: t.Any, depth=0) -> str:
        exp = super().explain(other, depth)
        gap = "".join(["\t"] * depth)
        if isinstance(other, dict):
            extra_keys = set(other.keys()) - set(self.params["type_map"].keys())
            if len(extra_keys) > 0:
                exp += "\n{}Found extra keys: {}".format(
                    gap, ",".join(list(extra_keys))
                )

            for key in self.params["type_map"]:
                val = other.get(key, None)
                if isinstance(self.params["type_map"][key].assign(val), InvalidType):
                    exp += "\n{}Key '{}':\n{}".format(
                        gap,
                        key,
                        self.params["type_map"][key].explain(val, depth=depth + 1),
                    )
        return exp

    def __repr__(self):
        return "{}".format(self.params["type_map"])


# Special Types
TypeRegistry.add(InvalidType)
TypeRegistry.add(AnyType)
TypeRegistry.add(UnknownType)

# Types with default type mappings
TypeRegistry.add(NoneType)
TypeRegistry.add(StringType)
TypeRegistry.add(TimestampType)
TypeRegistry.add(NumberType)
TypeRegistry.add(BooleanType)
TypeRegistry.add(ListType)
TypeRegistry.add(TypedDictType)

# Types without default type mappings
TypeRegistry.add(UnionType)
TypeRegistry.add(PythonObjectType)
TypeRegistry.add(ConstType)

# Common Industry Types
TypeRegistry.add(NDArrayType)

__all__ = [
    "TypeRegistry",
    "InvalidType",
    "UnknownType",
    "AnyType",
    "NoneType",
    "StringType",
    "NumberType",
    "TimestampType",
    "BooleanType",
    "ListType",
    "TypedDictType",
    "UnionType",
    "PythonObjectType",
    "ConstType",
    "OptionalType",
    "Type",
    "NDArrayType",
]
