// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::{
    PyBoolRef, PyDictRef, PyFloatRef, PyFragmentRef, PyIntRef, PyListRef, PyStrRef,
    PyStrSubclassRef, PyUuidRef,
};
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
use crate::typeref::{STR_TYPE, TRUE, VALUE_STR};
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
    dict: PyDictRef,
    state: SerializerState,
    #[allow(dead_code)]
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl DictGenericSerializer {
    pub fn new(
        dict: PyDictRef,
        state: SerializerState,
        default: Option<NonNull<crate::ffi::PyObject>>,
    ) -> Self {
        DictGenericSerializer {
            dict: dict,
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

        if self.dict.len() == 0 {
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
                $map.serialize_value(&StrSerializer::new(unsafe {
                    PyStrRef::from_ptr_unchecked($value)
                }))?;
            }
            ObType::StrSubclass => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&StrSubclassSerializer::new(unsafe {
                    PyStrSubclassRef::from_ptr_unchecked($value)
                }))?;
            }
            ObType::Int => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&IntSerializer::new(
                    unsafe { PyIntRef::from_ptr_unchecked($value) },
                    $self.state.opts(),
                ))?;
            }
            ObType::None => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&NoneSerializer::new()).unwrap();
            }
            ObType::Float => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&FloatSerializer::new(unsafe {
                    PyFloatRef::from_ptr_unchecked($value)
                }))?;
            }
            ObType::Bool => {
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&BoolSerializer::new(unsafe {
                    PyBoolRef::from_ptr_unchecked($value)
                }))
                .unwrap();
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
                $map.serialize_value(&UUID::new(unsafe { PyUuidRef::from_ptr_unchecked($value) }))
                    .unwrap();
            }
            ObType::Dict => {
                let pyvalue = DictGenericSerializer::new(
                    unsafe { PyDictRef::from_ptr_unchecked($value) },
                    $self.state,
                    $self.default,
                );
                $map.serialize_key($key).unwrap();
                $map.serialize_value(&pyvalue)?;
            }
            ObType::List => {
                if ffi!(Py_SIZE($value)) == 0 {
                    $map.serialize_key($key).unwrap();
                    $map.serialize_value(&ZeroListSerializer::new()).unwrap();
                } else {
                    let pyvalue = ListTupleSerializer::from_list(
                        unsafe { PyListRef::from_ptr_unchecked($value) },
                        $self.state,
                        $self.default,
                    );
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
                $map.serialize_value(&FragmentSerializer::new(unsafe {
                    PyFragmentRef::from_ptr_unchecked($value)
                }))?;
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
    dict: PyDictRef,
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

        pydict_next!(
            self.dict.as_ptr(),
            &raw mut pos,
            &raw mut next_key,
            &raw mut next_value
        );

        let mut map = serializer.serialize_map(None).unwrap();

        let len = self.dict.len();
        assume!(len > 0);

        for _ in 0..len {
            let key = next_key;
            let value = next_value;

            pydict_next!(
                self.dict.as_ptr(),
                &raw mut pos,
                &raw mut next_key,
                &raw mut next_value
            );

            // key
            let uni = PyStrRef::from_ptr(key)
                .map_err(|_| serde::ser::Error::custom(SerializeError::KeyMustBeStr))?
                .as_str();
            if uni.is_none() {
                cold_path!();
                err!(SerializeError::InvalidStr);
            }

            // value
            impl_serialize_entry!(map, self, uni.unwrap(), value);
        }

        map.end()
    }
}

pub(crate) struct DictSortedKey {
    dict: PyDictRef,
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

        pydict_next!(
            self.dict.as_ptr(),
            &raw mut pos,
            &raw mut next_key,
            &raw mut next_value
        );

        let len = self.dict.len();
        assume!(len > 0);

        let mut items: SmallVec<[(&str, *mut crate::ffi::PyObject); 8]> =
            SmallVec::with_capacity(len);

        for _ in 0..len {
            let key = next_key;
            let value = next_value;

            pydict_next!(
                self.dict.as_ptr(),
                &raw mut pos,
                &raw mut next_key,
                &raw mut next_value
            );

            if unsafe { !core::ptr::eq(ob_type!(key), STR_TYPE) } {
                err!(SerializeError::KeyMustBeStr)
            }
            let pystr = unsafe { PyStrRef::from_ptr_unchecked(key) };
            let uni = pystr.as_str();
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
#[cold]
#[inline(never)]
fn non_str_str(key: PyStrRef) -> Result<String, SerializeError> {
    // because of ObType::Enum
    match key.as_str() {
        Some(uni) => Ok(String::from(uni)),
        None => {
            cold_path!();
            Err(SerializeError::InvalidStr)
        }
    }
}

#[cold]
#[inline(never)]
fn non_str_str_subclass(key: PyStrSubclassRef) -> Result<String, SerializeError> {
    match key.as_str() {
        Some(uni) => Ok(String::from(uni)),
        None => {
            cold_path!();
            Err(SerializeError::InvalidStr)
        }
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
fn non_str_uuid(key: PyUuidRef) -> Result<String, SerializeError> {
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
        Ok(String::from(zmij::Buffer::new().format_finite(val)))
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
    dict: PyDictRef,
    state: SerializerState,
    default: Option<NonNull<crate::ffi::PyObject>>,
}

impl DictNonStrKey {
    fn pyobject_to_string(
        key: *mut crate::ffi::PyObject,
        opts: crate::opt::Opt,
    ) -> Result<String, SerializeError> {
        unsafe {
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
                ObType::Uuid => non_str_uuid(PyUuidRef::from_ptr_unchecked(key)),
                ObType::Enum => {
                    let value = ffi!(PyObject_GetAttr(key, VALUE_STR));
                    debug_assert!(ffi!(Py_REFCNT(value)) >= 2);
                    let ret = Self::pyobject_to_string(value, opts);
                    ffi!(Py_DECREF(value));
                    ret
                }
                ObType::Str => non_str_str(PyStrRef::from_ptr_unchecked(key)),
                ObType::StrSubclass => {
                    non_str_str_subclass(PyStrSubclassRef::from_ptr_unchecked(key))
                }
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

        pydict_next!(
            self.dict.as_ptr(),
            &raw mut pos,
            &raw mut next_key,
            &raw mut next_value
        );

        let opts = self.state.opts() & NOT_PASSTHROUGH;

        let len = self.dict.len();
        assume!(len > 0);

        let mut items: SmallVec<[(String, *mut crate::ffi::PyObject); 8]> =
            SmallVec::with_capacity(len);

        for _ in 0..len {
            let key = next_key;
            let value = next_value;

            pydict_next!(
                self.dict.as_ptr(),
                &raw mut pos,
                &raw mut next_key,
                &raw mut next_value
            );

            match PyStrRef::from_ptr(key) {
                Ok(pystr) => match pystr.as_str() {
                    Some(uni) => {
                        items.push((String::from(uni), value));
                    }
                    None => err!(SerializeError::InvalidStr),
                },
                Err(_) => match Self::pyobject_to_string(key, opts) {
                    Ok(key_as_str) => items.push((key_as_str, value)),
                    Err(err) => err!(err),
                },
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
