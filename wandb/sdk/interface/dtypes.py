import typing as t

if t.TYPE_CHECKING:
    from wandb.sdk.wandb_artifacts import Artifact as ArtifactInCreation
    from wandb.apis.public import Artifact as DownloadedArtifact


class TypeRegistry:
    """The TypeRegistry resolves python objects to Types as well as
    deserializes JSON dicts. Additional types can be registered via
    the .add call.
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
        TypeRegistry.types_by_class().update(
            {_type: wb_type for _type in wb_type.types}
        )

    @staticmethod
    def type_of(py_obj: t.Optional[t.Any]) -> "Type":
        class_handler = TypeRegistry.types_by_class().get(py_obj.__class__)
        _type = None
        if class_handler:
            _type = class_handler(py_obj)
        else:
            _type = ObjectType(py_obj)
        return _type

    @staticmethod
    def type_from_dict(
        json_dict: t.Dict[str, t.Any], artifact: t.Optional["DownloadedArtifact"] = None
    ) -> "Type":
        wb_type = json_dict.get("wb_type")
        if wb_type is None:
            TypeError("json_dict must contain `wb_type` key")
        _type = TypeRegistry.types_by_name().get(wb_type)
        if _type is None:
            TypeError("missing type handler for {}".format(wb_type))
        return _type.from_json(json_dict, artifact)


def _params_obj_to_json_obj(
    params_obj: t.Any, artifact: t.Optional["ArtifactInCreation"] = None,
) -> t.Any:
    """Helper method"""
    if params_obj.__class__ == dict:
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
    json_obj: t.Any, artifact: t.Optional["DownloadedArtifact"] = None
) -> t.Any:
    """Helper method"""
    if json_obj.__class__ == dict:
        if "wb_type" in json_obj:
            return TypeRegistry.type_from_dict(json_obj, artifact)
        else:
            return {
                key: _json_obj_to_params_obj(json_obj[key], artifact)
                for key in json_obj
            }
    elif json_obj.__class__ == list:
        return [_json_obj_to_params_obj(item, artifact) for item in json_obj]
    else:
        return json_obj


class Type(object):
    """This is the most generic type which all types are subclasses.
    It provides simple serialization and deserialization as well as equality checks.
    A name class-level property must be uniquely set by subclasses.
    """

    # Subclasses must override with a unique name. This is used to identify the
    # class during serializations and deserializations
    name: t.ClassVar[str] = ""

    # Subclasses may override with a list of `types` which this Type is capable
    # of being initialized. This is used by the Type Registry when calling `TypeRegistry.type_of`.
    # Some types will have an empty list - for example `Union`. There is no raw python type which
    # inherently maps to a Union and therefore the list should be empty.
    types: t.ClassVar[t.List[type]] = []

    # Contains the further specification of the Type
    params: t.Dict[str, t.Any]

    def __init__(
        self,
        py_obj: t.Optional[t.Any] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        """Initialize the type. Likely to be overridden by subtypes.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            params (dict, optional): [description]. The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        self.params = dict() if params is None else params

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        """Assign a python object to the type, returning a new type representing
        the result of the assignment.

        Must to be overridden by subclasses

        Args:
            py_obj (any, optional): Any python object which the user wishes to assign to
            this type

        Returns:
            Type: an instance of a subclass of the Type class.
        """
        raise NotImplementedError()

    def to_json(
        self, artifact: t.Optional["ArtifactInCreation"] = None
    ) -> t.Dict[str, t.Any]:
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
        artifact: t.Optional["DownloadedArtifact"] = None,
    ) -> "Type":
        """Construct a new instance of the type using a JSON dictionary equivalent to
        the kind output by `to_json`.

        If overridden by subclass, ensure that `to_json` is equivalently overridden.

        Returns:
            _Type: an instance of a subclass of the _Type class.
        """
        return cls(
            params=_json_obj_to_params_obj(json_dict.get("params", {}), artifact)
        )
        return cls()

    def __repr__(self):
        return "<WBType:{} | {}>".format(self.name, self.params)

    def __eq__(self, other):
        return self is other or (
            isinstance(self, Type)
            and isinstance(other, Type)
            and self.to_json() == other.to_json()
        )


class _NeverType(Type):
    """all assignments to a NeverType result in a Never Type.
    NeverType is basically the invalid case
    """

    name = "never"
    types: t.ClassVar[t.List[type]] = []

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "_NeverType":
        return self


# Singleton helper
NeverType = _NeverType()


class _AnyType(Type):
    """all assignments to an AnyType result in the
    AnyType except None which will be NeverType
    """

    name = "any"
    types: t.ClassVar[t.List[type]] = []

    def assign(
        self, py_obj: t.Union["Type", t.Optional[t.Any]] = None
    ) -> t.Union["_AnyType", _NeverType]:
        if isinstance(py_obj, Type):
            return (
                self
                if not (isinstance(py_obj, _NoneType) or isinstance(py_obj, _NeverType))
                else NeverType
            )
        else:
            return self if py_obj is not None else NeverType


class _UnknownType(Type):
    """all assignments to an UnknownType result in the type of the assigned object
    except none which will result in a NeverType
    """

    name = "unknown"
    types: t.ClassVar[t.List[type]] = []

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        if isinstance(py_obj, Type):
            return py_obj if not isinstance(py_obj, _NoneType) else NeverType
        else:
            return NeverType if py_obj is None else TypeRegistry.type_of(py_obj)


class _NoneType(Type):
    name = "none"
    types: t.ClassVar[t.List[type]] = [None.__class__]

    def assign(
        self, py_obj: t.Union["Type", t.Optional[t.Any]] = None
    ) -> t.Union["_NoneType", _NeverType]:
        if isinstance(py_obj, Type):
            return self if isinstance(py_obj, _NoneType) else NeverType
        else:
            return self if py_obj is None else NeverType


class _TextType(Type):
    name = "text"
    types: t.ClassVar[t.List[type]] = [str]

    def assign(
        self, py_obj: t.Union["Type", t.Optional[t.Any]] = None
    ) -> t.Union["_TextType", _NeverType]:
        if isinstance(py_obj, Type):
            return self if isinstance(py_obj, _TextType) else NeverType
        else:
            return self if py_obj.__class__ == str else NeverType


class _NumberType(Type):
    name = "number"
    types: t.ClassVar[t.List[type]] = [int, float]

    def assign(
        self, py_obj: t.Union["Type", t.Optional[t.Any]] = None
    ) -> t.Union["_NumberType", _NeverType]:
        if isinstance(py_obj, Type):
            return self if isinstance(py_obj, _NumberType) else NeverType
        else:
            return self if py_obj.__class__ in [int, float] else NeverType


class _BooleanType(Type):
    name = "boolean"
    types: t.ClassVar[t.List[type]] = [bool]

    def assign(
        self, py_obj: t.Union["Type", t.Optional[t.Any]] = None
    ) -> t.Union["_BooleanType", _NeverType]:
        if isinstance(py_obj, Type):
            return self if isinstance(py_obj, _BooleanType) else NeverType
        else:
            return self if py_obj.__class__ == bool else NeverType


# Singleton Helpers
AnyType = _AnyType()
UnknownType = _UnknownType()
NoneType = _NoneType()
TextType = _TextType()
NumberType = _NumberType()
BooleanType = _BooleanType()


def _flatten_union_types(allowed_types: t.List[Type]) -> t.List[Type]:
    final_types = []
    for allowed_type in allowed_types:
        if isinstance(allowed_type, UnionType):
            internal_types = _flatten_union_types(allowed_type.params["allowed_types"])
            for internal_type in internal_types:
                final_types.append(internal_type)
        else:
            final_types.append(allowed_type)
    return final_types


def _union_assigner(
    allowed_types: t.List[Type], item: t.Union[Type, t.Optional[t.Any]]
):
    resolved_types = []
    valid = False
    unknown_count = 0

    for allowed_type in allowed_types:
        if valid:
            resolved_types.append(allowed_type)
        else:
            if isinstance(allowed_type, _UnknownType):
                unknown_count += 1
            else:
                assigned_type = allowed_type.assign(item)
                if assigned_type == NeverType:
                    resolved_types.append(allowed_type)
                else:
                    resolved_types.append(assigned_type)
                    valid = True

    if not valid:
        if unknown_count == 0:
            return NeverType
        else:
            new_type = UnknownType.assign(item)
            if new_type == NeverType:
                return NeverType
            else:
                resolved_types.append(new_type)
                unknown_count -= 1

    for _ in range(unknown_count):
        resolved_types.append(UnknownType)

    resolved_types = _flatten_union_types(resolved_types)
    resolved_types.sort(key=str)
    return resolved_types


class UnionType(Type):
    """Represents an "or" of types
    """

    name = "union"
    types: t.ClassVar[t.List[type]] = []

    def __init__(
        self,
        py_obj: t.Optional[t.List[Type]] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert py_obj is None or (
            py_obj.__class__ == list
            and all([isinstance(item, Type) for item in py_obj])
        )
        assert params is None or (
            params.__class__ == dict
            and all(
                [isinstance(item, Type) for item in params.get("allowed_types", [])]
            )
        )

        if params is None:
            params = {"allowed_types": py_obj}

        params["allowed_types"] = _flatten_union_types(params["allowed_types"])
        params["allowed_types"].sort(key=str)

        super(UnionType, self).__init__(py_obj, params)

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        if isinstance(py_obj, UnionType):
            assignees = py_obj.params["allowed_types"]
        else:
            assignees = [py_obj]

        resolved_types = self.params.get("allowed_types", [])
        for assignee in assignees:
            resolved_types = _union_assigner(
                self.params.get("allowed_types", []), assignee
            )
            if resolved_types == NeverType:
                return NeverType

        return self.__class__(resolved_types)


def OptionalType(wb_type: Type) -> UnionType:  # noqa: N802
    """Function that mimics the Type class API for constructing an "Optional Type"
    which is just a Union[wb_type, NoneType]

    Args:
        wb_type (Type): type to be optional

    Returns:
        Type: Optional version of the type.
    """
    return UnionType([wb_type, NoneType])


class ObjectType(Type):
    """Serves as a backup type by keeping track of the python object name"""

    name = "object"
    types: t.ClassVar[t.List[type]] = []

    def __init__(
        self,
        py_obj: t.Optional[t.Any] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert params is None or (
            params.__class__ == dict and len(params.get("class_name", "")) > 0
        )

        if params is None:
            params = {"class_name": py_obj.__class__.__name__}

        super(ObjectType, self).__init__(py_obj, params)

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        if (
            isinstance(py_obj, ObjectType)
            and py_obj.params["class_name"] == self.params["class_name"]
        ) or (py_obj.__class__.__name__ == self.params["class_name"]):
            return self
        else:
            return NeverType


class ListType(Type):
    """Represents a list of homogenous types
    """

    name = "list"
    types: t.ClassVar[t.List[type]] = [list, tuple, set, frozenset]

    def __init__(
        self,
        py_obj: t.Optional[t.List[t.Any]] = None,
        dtype: t.Optional[Type] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        """Initialize the ListType.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            dtype (Type, optional); The dtype of the list. Overrides py_obj
            params (dict, optional): [description]. The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        assert py_obj is None or py_obj.__class__ in [list, tuple, set, frozenset]

        assert params is None or (
            params.__class__ == dict and isinstance(params.get("element_type"), Type)
        )

        assert dtype is None or isinstance(dtype, Type)

        if params is None:
            if dtype is not None:
                params = {"element_type": dtype}
            elif py_obj is None:
                params = {"element_type": UnknownType}
            elif (  # yes, this is a bit verbose, but the mypy typechecker likes it this way
                isinstance(py_obj, list)
                or isinstance(py_obj, tuple)
                or isinstance(py_obj, set)
                or isinstance(py_obj, frozenset)
            ):
                py_list = list(py_obj)
                elm_type = (
                    UnknownType if None not in py_list else OptionalType(UnknownType)
                )
                for item in py_list:
                    _elm_type = elm_type.assign(item)
                    if _elm_type is NeverType:
                        raise TypeError(
                            "List contained incompatible types. Expected type {} found item {}".format(
                                elm_type, item
                            )
                        )

                    elm_type = _elm_type

                params = {"element_type": elm_type}

        super(ListType, self).__init__(py_obj, params)

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        if isinstance(py_obj, ListType):
            assigned_type = self.params["element_type"].assign(
                py_obj.params["element_type"]
            )
            if assigned_type == NeverType:
                return NeverType
            else:
                return ListType(dtype=assigned_type)
        elif (  # yes, this is a bit verbose, but the mypy typechecker likes it this way
            isinstance(py_obj, list)
            or isinstance(py_obj, tuple)
            or isinstance(py_obj, set)
            or isinstance(py_obj, frozenset)
        ):
            new_element_type = self.params["element_type"]
            for obj in list(py_obj):
                new_element_type = new_element_type.assign(obj)
                if new_element_type == NeverType:
                    return NeverType
            return ListType(dtype=new_element_type)
        else:
            return NeverType


class KeyPolicy:
    EXACT = "E"  # require exact key match
    SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
    UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown


# KeyPolicyType = t.Literal[KeyPolicy.EXACT, KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]


class DictType(Type):
    """Represents a dictionary object where each key can have a type
    """

    name = "dictionary"
    types: t.ClassVar[t.List[type]] = [dict]

    def __init__(
        self,
        py_obj: t.Optional[t.Dict[str, t.Any]] = None,
        key_policy: str = KeyPolicy.EXACT,
        dtype: t.Optional[t.Dict[str, t.Any]] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        """Initialize the DictType.

        Args:
            py_obj (any, optional): The python object to construct the type from. Defaults to None.
            key_policy (str): Key policy from KeyPolicy
                ```
                    EXACT = "E"  # require exact key match
                    SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
                    UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown
                ```
            dtype (dict, optional): A dict-like object with values for each key as either a dictionary, Type, or list. Will override py_obj.
            params (dict, optional): The params for the type. If present, all other fields are ignored.
                This is not meant to be used be external parties, and is used by for deserialization. Defaults to None.
        """
        # TODO Parameter validation
        if params is None:
            if dtype is not None:
                new_type_map: t.Dict[str, Type] = {}
                for key in dtype:
                    # Allows for nested dict notation
                    if dtype[key].__class__ == dict:
                        new_type_map[key] = DictType(
                            dtype=dtype[key], key_policy=key_policy
                        )
                    # allows for nested list notation
                    elif dtype[key].__class__ == list:
                        ptr = dtype[key]
                        depth = 0
                        while ptr.__class__ == list and len(ptr) > 0:
                            if len(ptr) > 1:
                                raise TypeError(
                                    "Lists in DictType's dtype must be of length 0 or 1"
                                )
                            else:
                                depth += 1
                                ptr = ptr[0]

                        if ptr.__class__ == list:
                            inner_type: Type = ListType()
                        elif ptr.__class__ == dict:
                            inner_type = DictType(dtype=ptr, key_policy=key_policy)
                        elif isinstance(ptr, Type):
                            inner_type = ptr
                        else:
                            raise TypeError(
                                "DictType dtype values must subclass Type (or be a dict or list). Found {} of class {}".format(
                                    dtype[key], dtype[key].__class__
                                )
                            )
                        for _ in range(depth):
                            inner_type = ListType(dtype=inner_type)
                        new_type_map[key] = inner_type
                    elif isinstance(dtype[key], Type):
                        new_type_map[key] = dtype[key]
                    else:
                        raise TypeError(
                            "DictType dtype values must subclass Type (or be a dict or list). Found {} of class {}".format(
                                dtype[key], dtype[key].__class__
                            )
                        )
                params = {"type_map": new_type_map, "policy": key_policy}
            elif py_obj is not None:
                params = {
                    "type_map": {
                        key: TypeRegistry.type_of(py_obj[key]) for key in py_obj
                    },
                    "policy": key_policy,
                }
            else:
                params = {"type_map": {}, "policy": key_policy}

        super(DictType, self).__init__(py_obj, params)

    def assign(self, py_obj: t.Optional[t.Any] = None) -> "Type":
        if isinstance(py_obj, DictType):
            if py_obj.params["policy"] != self.params["policy"]:
                return NeverType
            py_obj = py_obj.params["type_map"]
        else:
            if py_obj is None or py_obj.__class__ not in self.types:
                return NeverType

        new_type_map = {}
        type_map = self.params.get("type_map", {})
        policy = self.params.get("policy", KeyPolicy.EXACT)

        for key in type_map:
            if key in py_obj:
                new_type = type_map[key].assign(py_obj[key])
                if new_type == NeverType:
                    return NeverType
                else:
                    new_type_map[key] = new_type
            else:
                # Treat a missing key as if it is a None value.
                new_type = type_map[key].assign(None)
                if new_type == NeverType:
                    if policy in [KeyPolicy.EXACT]:
                        return NeverType
                    elif policy in [KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]:
                        new_type_map[key] = type_map[key]
                else:
                    new_type_map[key] = new_type

        for key in py_obj:
            if key not in new_type_map:
                if policy in [KeyPolicy.EXACT, KeyPolicy.SUBSET]:
                    return NeverType
                elif policy in [KeyPolicy.UNRESTRICTED]:
                    if isinstance(py_obj[key], Type):
                        new_type_map[key] = py_obj[key]
                    elif py_obj[key].__class__ == dict:
                        new_type_map[key] = DictType(py_obj[key], policy)
                    else:
                        new_type_map[key] = TypeRegistry.type_of(py_obj[key])

        return DictType(dtype=new_type_map, key_policy=policy)


class ConstType(Type):
    """Represents a constant value (currently only primitives supported)
    """

    name = "const"
    types: t.ClassVar[t.List[type]] = []

    def __init__(
        self,
        py_obj: t.Optional[t.Any] = None,
        params: t.Optional[t.Dict[str, t.Any]] = None,
    ):
        if py_obj is None and params is None:
            raise TypeError("Both py_obj and params cannot be none")
        assert py_obj is None or py_obj.__class__ in [str, int, float, bool, set, list]
        assert params is None or (
            params.__class__ == dict and params.get("val") is not None
        )

        if params is None:
            params = {"val": py_obj}
            if isinstance(py_obj, set):
                params["is_set"] = True
        else:
            if params.get("is_set", False):
                params["val"] = set(params["val"])

        super(ConstType, self).__init__(py_obj, params)

    def assign(self, py_obj: t.Union["Type", t.Optional[t.Any]] = None) -> "Type":
        if isinstance(py_obj, ConstType):
            valid = self.params.get("val") == py_obj.params.get("val")
        else:
            valid = self.params.get("val") == py_obj
        return self if valid else NeverType


# Special Types
TypeRegistry.add(_NeverType)
TypeRegistry.add(_AnyType)
TypeRegistry.add(_UnknownType)

# Types with default type mappings
TypeRegistry.add(_NoneType)
TypeRegistry.add(_TextType)
TypeRegistry.add(_NumberType)
TypeRegistry.add(_BooleanType)
TypeRegistry.add(ListType)
TypeRegistry.add(DictType)

# Types without default type mappings
TypeRegistry.add(UnionType)
TypeRegistry.add(ObjectType)
TypeRegistry.add(ConstType)

__all__ = [
    "TypeRegistry",
    "NeverType",
    "UnknownType",
    "AnyType",
    "NoneType",
    "TextType",
    "NumberType",
    "BooleanType",
    "ListType",
    "DictType",
    "KeyPolicy",
    "UnionType",
    "ObjectType",
    "ConstType",
    "OptionalType",
    "Type",
]
