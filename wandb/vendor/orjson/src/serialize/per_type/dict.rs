// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025), Aviram Hassan (2020)

use crate::opt::{NON_STR_KEYS, NOT_PASSTHROUGH, SORT_KEYS, SORT_OR_NON_STR_KEYS};
use crate::serialize::buffer::SmallFixedBuffer;
use crate::serialize::error::SerializeError;
use crate::serialize::obtype::{ObType, pyobject_to_obtype};
use crate::serialize::per_type::datetimelike::DateTimeLike;
use crate::serialize::per_type::{
    BoolSerializer, DataclassGenericSerializer, Date, DateTime, DefaultSerializer, EnumSerializer,
    FloatSerializer, FragmentSerializer, IntSerializer, ListTupleSerializer, NoneSerializer,
    NumpyScalar, NumpySerializer, StrSerializer, StrSubclassSerializer, Time, UUID,
    ZeroListSerializer,
};
use crate::serialize::serializer::PyObjectSerializer;
use crate::serialize::state::SerializerState;
use crate::str::{PyStr, PyStrSubclass};
use crate::typeref::{STR_TYPE, TRUE, VALUE_STR};
use crate::util::isize_to_usize;
use core::ptr::NonNull;
use serde::ser::{Serialize, SerializeMap, Serializer};
use smallvec::SmallVec;

pub(crate) struct ZeroDictSerializer;

impl ZeroDictSerializer {
    pub const fn new() -> Self {
        Self {}
    }
}

impl Serialize for ZeroDictSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_bytes(b"{}")
    }
}

pub(crate) struct DictGenericSerializer {
    ptr: *mut crate::ffi::PyObject,
    state: SerializerState,
    #[allow(dead_code)]
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl DictGenericSerializer {
    pub fn new(
        ptr: *mut crate::ffi::PyObject,
        state: SerializerState,
        default: Option<NonNull<crate::ffi::PyObject>>,
    ) -> Self {
        DictGenericSerializer {
            ptr: ptr,
            state: state.copy_for_recursive_call(),
            default: default,
        }
    }
}

impl Serialize for DictGenericSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.state.recursion_limit() {
            cold_path!();
            err!(SerializeError::RecursionLimit)
        }

        if ffi!(Py_SIZE(self.ptr)) == 0 {
            cold_path!();
            ZeroDictSerializer::new().serialize(serializer)
        } else if opt_disabled!(self.state.opts(), SORT_OR_NON_STR_KEYS) {
            unsafe {
                (*(core::ptr::from_ref::<DictGenericSerializer>(self)).cast::<Dict>())
                    .serialize(serializer)
            }
        } else if opt_enabled!(self.state.opts(), NON_STR_KEYS) {
            unsafe {
                (*(core::ptr::from_ref::<DictGenericSerializer>(self)).cast::<DictNonStrKey>())
                    .serialize(serializer)
            }
        } else {
            unsafe {
                (*(core::ptr::from_ref::<DictGenericSerializer>(self)).cast::<DictSortedKey>())
                    .serialize(serializer)
            }
        }
    }
}

macro_rules! impl_serialize_entry {
    ($map:expr, $self:expr, $key:expr, $value:expr) => {
        match pyobject_to_obtype($value, $self.state.opts()) {
            ObType::Str => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&StrSerializer::new($value))?;
            }
            ObType::StrSubclass => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&StrSubclassSerializer::new($value))?;
            }
            ObType::Int => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&IntSerializer::new($value, $self.state.opts()))?;
            }
            ObType::None => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&NoneSerializer::new()).unwrap();
            }
            ObType::Float => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&FloatSerializer::new($value, $self.state.opts()))?;
            }
            ObType::Bool => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&BoolSerializer::new($value)).unwrap();
            }
            ObType::Datetime => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&DateTime::new($value, $self.state.opts()))?;
            }
            ObType::Date => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&Date::new($value))?;
            }
            ObType::Time => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&Time::new($value, $self.state.opts()))?;
            }
            ObType::Uuid => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&UUID::new($value)).unwrap();
            }
            ObType::Dict => {
                let pyvalue = DictGenericSerializer::new($value, $self.state, $self.default);
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&pyvalue)?;
            }
            ObType::List => {
                if ffi!(Py_SIZE($value)) == 0 {
                    $map.serialize_key($key).unwrap();
                    $map.serialize_value(&ZeroListSerializer::new()).unwrap();
                } else {
                    let pyvalue =
                        ListTupleSerializer::from_list($value, $self.state, $self.default);
                    $map.serialize_key($key).unwrap();
                    $map.serialize_value(&pyvalue)?;
                }
            }
            ObType::Tuple => {
                if ffi!(Py_SIZE($value)) == 0 {
                    $map.serialize_key($key).unwrap();
                    $map.serialize_value(&ZeroListSerializer::new()).unwrap();
                } else {
                    let pyvalue =
                        ListTupleSerializer::from_tuple($value, $self.state, $self.default);
                    $map.serialize_key($key).unwrap();
                    $map.serialize_value(&pyvalue)?;
                }
            }
            ObType::Dataclass => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&DataclassGenericSerializer::new(&PyObjectSerializer::new(
                    $value,
                    $self.state,
                    $self.default,
                )))?;
            }
            ObType::Enum => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&EnumSerializer::new(&PyObjectSerializer::new(
                    $value,
                    $self.state,
                    $self.default,
                )))?;
            }
            ObType::NumpyArray => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&NumpySerializer::new(&PyObjectSerializer::new(
                    $value,
                    $self.state,
                    $self.default,
                )))?;
            }
            ObType::NumpyScalar => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&NumpyScalar::new($value, $self.state.opts()))?;
            }
            ObType::Fragment => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&FragmentSerializer::new($value))?;
            }
            ObType::Unknown => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&DefaultSerializer::new(&PyObjectSerializer::new(
                    $value,
                    $self.state,
                    $self.default,
                )))?;
            }
        }
    };
}

pub(crate) struct Dict {
    ptr: *mut crate::ffi::PyObject,
    state: SerializerState,
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl Serialize for Dict {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut pos = 0;
        let mut next_key: *mut crate::ffi::PyObject = core::ptr::null_mut();
        let mut next_value: *mut crate::ffi::PyObject = core::ptr::null_mut();

        pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

        let mut map = serializer.serialize_map(None).unwrap();

        let len = isize_to_usize(ffi!(Py_SIZE(self.ptr)));
        assume!(len > 0);

        for _ in 0..len {
            let key = next_key;
            let value = next_value;

            pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

            // key
            let key_ob_type = ob_type!(key);
            if !is_class_by_type!(key_ob_type, STR_TYPE) {
                err!(SerializeError::KeyMustBeStr)
            }
            let pystr = unsafe { PyStr::from_ptr_unchecked(key) };
            let uni = pystr.to_str();
            if uni.is_none() {
                err!(SerializeError::InvalidStr)
            }
            let key_as_str = uni.unwrap();

            // value
            impl_serialize_entry!(map, self, key_as_str, value);
        }

        map.end()
    }
}

pub(crate) struct DictSortedKey {
    ptr: *mut crate::ffi::PyObject,
    state: SerializerState,
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl Serialize for DictSortedKey {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut pos = 0;
        let mut next_key: *mut crate::ffi::PyObject = core::ptr::null_mut();
        let mut next_value: *mut crate::ffi::PyObject = core::ptr::null_mut();

        pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

        let len = isize_to_usize(ffi!(Py_SIZE(self.ptr)));
        assume!(len > 0);

        let mut items: SmallVec<[(&str, *mut crate::ffi::PyObject); 8]> =
            SmallVec::with_capacity(len);

        for _ in 0..len as usize {
            let key = next_key;
            let value = next_value;

            pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

            if unsafe { !core::ptr::eq(ob_type!(key), STR_TYPE) } {
                err!(SerializeError::KeyMustBeStr)
            }
            let pystr = unsafe { PyStr::from_ptr_unchecked(key) };
            let uni = pystr.to_str();
            if uni.is_none() {
                err!(SerializeError::InvalidStr)
            }
            let key_as_str = uni.unwrap();

            items.push((key_as_str, value));
        }

        sort_dict_items(&mut items);

        let mut map = serializer.serialize_map(None).unwrap();
        for (key, val) in items.iter() {
            let pyvalue = PyObjectSerializer::new(*val, self.state, self.default);
            map.serialize_key(key).unwrap();
            map.serialize_value(&pyvalue)?;
        }
        map.end()
    }
}

#[inline(never)]
fn non_str_str(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    // because of ObType::Enum
    let uni = unsafe { PyStr::from_ptr_unchecked(key).to_str() };
    if uni.is_none() {
        Err(SerializeError::InvalidStr)
    } else {
        Ok(String::from(uni.unwrap()))
    }
}

#[cold]
#[inline(never)]
fn non_str_str_subclass(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    let uni = unsafe { PyStrSubclass::from_ptr_unchecked(key).to_str() };
    if uni.is_none() {
        Err(SerializeError::InvalidStr)
    } else {
        Ok(String::from(uni.unwrap()))
    }
}

#[allow(clippy::unnecessary_wraps)]
#[inline(never)]
fn non_str_date(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    let mut buf = SmallFixedBuffer::new();
    Date::new(key).write_buf(&mut buf);
    let key_as_str = str_from_slice!(buf.as_ptr(), buf.len());
    Ok(String::from(key_as_str))
}

#[inline(never)]
fn non_str_datetime(
    key: *mut crate::ffi::PyObject,
    opts: crate::opt::Opt,
) -> Result<String, SerializeError> {
    let mut buf = SmallFixedBuffer::new();
    let dt = DateTime::new(key, opts);
    if dt.write_buf(&mut buf, opts).is_err() {
        return Err(SerializeError::DatetimeLibraryUnsupported);
    }
    let key_as_str = str_from_slice!(buf.as_ptr(), buf.len());
    Ok(String::from(key_as_str))
}

#[cold]
#[inline(never)]
fn non_str_time(
    key: *mut crate::ffi::PyObject,
    opts: crate::opt::Opt,
) -> Result<String, SerializeError> {
    let mut buf = SmallFixedBuffer::new();
    let time = Time::new(key, opts);
    if time.write_buf(&mut buf).is_err() {
        return Err(SerializeError::TimeHasTzinfo);
    }
    let key_as_str = str_from_slice!(buf.as_ptr(), buf.len());
    Ok(String::from(key_as_str))
}

#[allow(clippy::unnecessary_wraps)]
#[inline(never)]
fn non_str_uuid(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    let mut buf = SmallFixedBuffer::new();
    UUID::new(key).write_buf(&mut buf);
    let key_as_str = str_from_slice!(buf.as_ptr(), buf.len());
    Ok(String::from(key_as_str))
}

#[allow(clippy::unnecessary_wraps)]
#[cold]
#[inline(never)]
fn non_str_float(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    let val = ffi!(PyFloat_AS_DOUBLE(key));
    if !val.is_finite() {
        Ok(String::from("null"))
    } else {
        Ok(String::from(ryu::Buffer::new().format_finite(val)))
    }
}

#[allow(clippy::unnecessary_wraps)]
#[inline(never)]
fn non_str_int(key: *mut crate::ffi::PyObject) -> Result<String, SerializeError> {
    let ival = ffi!(PyLong_AsLongLong(key));
    if ival == -1 && !ffi!(PyErr_Occurred()).is_null() {
        cold_path!();
        ffi!(PyErr_Clear());
        let uval = ffi!(PyLong_AsUnsignedLongLong(key));
        if uval == u64::MAX && !ffi!(PyErr_Occurred()).is_null() {
            return Err(SerializeError::DictIntegerKey64Bit);
        }
        Ok(String::from(itoa::Buffer::new().format(uval)))
    } else {
        Ok(String::from(itoa::Buffer::new().format(ival)))
    }
}

#[inline(never)]
fn sort_dict_items(items: &mut SmallVec<[(&str, *mut crate::ffi::PyObject); 8]>) {
    items.sort_unstable_by(|a, b| a.0.cmp(b.0));
}

pub(crate) struct DictNonStrKey {
    ptr: *mut crate::ffi::PyObject,
    state: SerializerState,
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl DictNonStrKey {
    fn pyobject_to_string(
        key: *mut crate::ffi::PyObject,
        opts: crate::opt::Opt,
    ) -> Result<String, SerializeError> {
        match pyobject_to_obtype(key, opts) {
            ObType::None => Ok(String::from("null")),
            ObType::Bool => {
                if unsafe { core::ptr::eq(key, TRUE) } {
                    Ok(String::from("true"))
                } else {
                    Ok(String::from("false"))
                }
            }
            ObType::Int => non_str_int(key),
            ObType::Float => non_str_float(key),
            ObType::Datetime => non_str_datetime(key, opts),
            ObType::Date => non_str_date(key),
            ObType::Time => non_str_time(key, opts),
            ObType::Uuid => non_str_uuid(key),
            ObType::Enum => {
                let value = ffi!(PyObject_GetAttr(key, VALUE_STR));
                debug_assert!(ffi!(Py_REFCNT(value)) >= 2);
                let ret = Self::pyobject_to_string(value, opts);
                ffi!(Py_DECREF(value));
                ret
            }
            ObType::Str => non_str_str(key),
            ObType::StrSubclass => non_str_str_subclass(key),
            ObType::Tuple
            | ObType::NumpyScalar
            | ObType::NumpyArray
            | ObType::Dict
            | ObType::List
            | ObType::Dataclass
            | ObType::Fragment
            | ObType::Unknown => Err(SerializeError::DictKeyInvalidType),
        }
    }
}

impl Serialize for DictNonStrKey {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut pos = 0;
        let mut next_key: *mut crate::ffi::PyObject = core::ptr::null_mut();
        let mut next_value: *mut crate::ffi::PyObject = core::ptr::null_mut();

        pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

        let opts = self.state.opts() & NOT_PASSTHROUGH;

        let len = isize_to_usize(ffi!(Py_SIZE(self.ptr)));
        assume!(len > 0);

        let mut items: SmallVec<[(String, *mut crate::ffi::PyObject); 8]> =
            SmallVec::with_capacity(len);

        for _ in 0..len {
            let key = next_key;
            let value = next_value;

            pydict_next!(self.ptr, &mut pos, &mut next_key, &mut next_value);

            if is_type!(ob_type!(key), STR_TYPE) {
                match unsafe { PyStr::from_ptr_unchecked(key).to_str() } {
                    Some(uni) => {
                        items.push((String::from(uni), value));
                    }
                    None => err!(SerializeError::InvalidStr),
                }
            } else {
                match Self::pyobject_to_string(key, opts) {
                    Ok(key_as_str) => items.push((key_as_str, value)),
                    Err(err) => err!(err),
                }
            }
        }

        let mut items_as_str: SmallVec<[(&str, *mut crate::ffi::PyObject); 8]> =
            SmallVec::with_capacity(len);
        items
            .iter()
            .for_each(|(key, val)| items_as_str.push(((*key).as_str(), *val)));

        if opt_enabled!(opts, SORT_KEYS) {
            sort_dict_items(&mut items_as_str);
        }

        let mut map = serializer.serialize_map(None).unwrap();
        for (key, val) in items_as_str.iter() {
            let pyvalue = PyObjectSerializer::new(*val, self.state, self.default);
            map.serialize_key(key).unwrap();
            map.serialize_value(&pyvalue)?;
        }
        map.end()
    }
}
