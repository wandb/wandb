def obj_assign(a, b, dict_fn, list_fn):
    if a.__class__ != b.__class__:
        return False
    elif a.__class__ == dict:
        return dict_fn(a, b)
    elif a.__class__ == list:
        return list_fn(a, b)
    elif a != b:
        return False
    else:
        return a
        
def list_assign_strict(a, b):
    if len(a) != len(b):
        return False
    else:
        ret_list = []
        for i in range(len(a)):
            item = obj_assign(a[i], b[i], dict_assign_strict, list_assign_strict)
            if item is False:
                return False
            else:
                ret_list.append(item)
        return ret_list

def dict_assign_strict(a, b):
    ret = {}
    for key in a:
        if key not in b:
            return False
        else:
            ret[key] = obj_assign(a[key], b[key], dict_assign_strict, list_assign_strict)

    for key in b:
        if key not in key:
            return False

    return ret

def list_assign_subset(a, b):
    if len(a) > len(b):
        return False
    else:
        ret_list = []
        for i in range(len(b)):
            if i < len(a):
                item = obj_assign(a[i], b[i], dict_assign_subset, list_assign_subset)
                if item is False:
                    return False
                else:
                    ret_list.append(item)
            else:
                ret_list.append(b[i])

        return ret_list

def dict_assign_subset(a, b):
    ret = {}
    for key in a:
        if key not in b:
            return False
        else:
            ret[key] = obj_assign(a[key], b[key], dict_assign_subset, list_assign_subset)

    for key in b:
        if key not in a:
            ret[key] = b[key]

    return ret


def list_assign_non_conflict(a, b):
    ret_list = []
    for i in range(max(len(a), len(b))):
        if i < len(a) and i < len(b):
            item = obj_assign(a[i], b[i], dict_assign_non_conflict, list_assign_non_conflict)
            if item is False:
                return False
            else:
                ret_list.append(item)
        else:
            if i < len(a):
                ret_list.append(a[i])
            else:
                ret_list.append(b[i])

    return ret_list

def dict_assign_non_conflict(a, b):
    ret = {}
    for key in a:
        if key in b:
            ret[key] = obj_assign(a[key], b[key], dict_assign_non_conflict, list_assign_non_conflict)
        else:
            ret[key] = a[key]

    for key in b:
        if key not in a:
            ret[key] = b[key]

    return ret


outer = {
    "a": 1,
    "b": 2,
    "c": 3
}

left = {
    "a": 1,
    "b": 2,
}

right = {
    "b": 2,
    "c": 3
}

inner = {
    "b": 2,
}


assert dict_assign_strict(outer, outer) == outer
assert dict_assign_strict(outer, left) == False
assert dict_assign_strict(outer, right) == False
assert dict_assign_strict(outer, inner) == False

assert dict_assign_non_conflict(outer, outer) == outer
assert dict_assign_non_conflict(outer, left) == outer
assert dict_assign_non_conflict(outer, right) == outer
assert dict_assign_non_conflict(outer, inner) == outer

assert dict_assign_non_conflict(inner, inner) == inner
assert dict_assign_non_conflict(left, right) == outer

assert dict_assign_subset(outer, outer) == outer
assert dict_assign_subset(outer, left) == False
assert dict_assign_subset(outer, right) == False
assert dict_assign_subset(outer, inner) == False

assert dict_assign_subset(inner, inner) == inner
assert dict_assign_subset(left, right) == False
assert dict_assign_subset(left, outer) == outer
assert dict_assign_subset(right, outer) == outer
assert dict_assign_subset(inner, outer) == outer

outer = [1,2,3]
left = [1,2]
right = [2,3]

assert list_assign_strict(outer, outer) == outer
assert list_assign_strict(left, outer) == False
assert list_assign_strict(left, outer) == False

assert list_assign_non_conflict(outer, outer) == outer
assert list_assign_non_conflict(left, outer) == outer
assert list_assign_non_conflict(outer, left) == outer
assert list_assign_non_conflict(left, right) == False

assert list_assign_subset(outer, outer) == outer
assert list_assign_subset(left, outer) == outer
assert list_assign_subset(outer, left) == False
assert list_assign_subset(right, outer) == False

class WBAnyType:
    _type_id = "any"
    _optional = True # should be boolean value
    _meta = None # should be dict value (or type?)

    def __init__(self, optional=True, meta=None):
        self._optional = optional
        self._meta = meta if meta is not None else {}

    @property
    def type_id(self):
        return self._type_id

    @property
    def to_dict(self):
        return {
            "_type_id": self._type_id,
            "_optional": self._optional,
            "_meta": self._meta,
        }

    def assign(self, other_type):
        if self._type_id == other_type._type_id:
            return self._assign_meta(other._meta)
        elif other_type.__class__ == WBNoneType and self._optional is False:
            return False
        else:
            return self
    
    # Should be overriden for complex types
    def _assign_meta(self, other_meta):
        return obj_assign(self._meta, other_meta, dict_assign_strict, list_assign_strict)

    def bind(self, data):
        self._meta = {}

    @staticmethod
    def validate_data(data):
        return True

class WBNoneType(WBAnyType):
    _type_id = "none"

    @staticmethod
    def validate_data(data):
        return data is None


class WBNumberType(WBType):
    _type_id = "number"

    @staticmethod
    def validate_data(data):
        return type(data) in [int, float, complex]
    
class WBTextType(WBType):
    _type_id = "text"

    @staticmethod
    def validate_data(data):
        return type(data) == str

class WBBooleanType(WBType):
    _type_id = "boolean"

    @staticmethod
    def validate_data(data):
        return type(data) == bool


# class WBDictType(WBAnyType):
#     pass

class WBListType(WBAnyType):
    _type_id = "list"

    @staticmethod
    def validate_data(data):
        return type(data) in [list, tuple, set, frozenset]

    # Should be overriden for complex types
    def _assign_meta(self, other_meta):
        return obj_assign(self._meta, other_meta, dict_assign_strict, list_assign_strict)

    def bind(self, data):
        element_type = WBAnyType()
        for item in data:
            element_type = element_type.assign(WBValue(item)._type)

        self._meta = {
            "element_type": element_type
        }



class WBValue:
    _type = None
    _data = None
    
    def __init__(self, data, wb_type=None):
        if wb_type is None:
            self._type = WBValue.python_obj_to_wb_type(data)
        else:
            if wb_type.validate_data(data):
                self._type = wb_type
            else:
                raise TypeError("Type does not support data")

        self._type.bind(data)
        self._data = data

    @staticmethod
    def python_obj_to_wb_type(data):
        if not hasattr(WBValue, "__registered_types"):
            raise TypeError("No Types Registered!!!")
        else:
            for wb_type in WBValue.__registered_types:
                if wb_type.validate_data(data):
                    return wb_type()

    @property
    def type_id(self):
        return self._type.type_id

    @property
    def meta(self):
        return self._type.meta

    @property
    def data(self):
        return self._data
    
    def to_dict(self, include_type=True):
        result = {
            "data": self.data
        }
        if include_type:
            result["__wb_type"] = self.meta
        return result

    @classmethod
    def from_dict(cls, obj):
        return cls(obj["data"])

    @staticmethod
    def register_type(wb_type):
        if not hasattr(WBValue, "__registered_types"):
            WBValue.__registered_types = set()
        
        WBValue.__registered_types.add(wb_type)

WBValue.register_type(WBAnyType)
WBValue.register_type(WBNoneType)
WBValue.register_type(WBNumberType)
WBValue.register_type(WBTextType)
WBValue.register_type(WBBooleanType)
WBValue.register_type(WBListType)


        # elif type(data) == dict:
        # check to see if the dict contains a __wb_type key
        #     return 