// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::opt::{APPEND_NEWLINE, INDENT_2, Opt};
use crate::serialize::obtype::{ObType, pyobject_to_obtype};
use crate::serialize::per_type::{
    BoolSerializer, DataclassGenericSerializer, Date, DateTime, DefaultSerializer,
    DictGenericSerializer, EnumSerializer, FloatSerializer, FragmentSerializer, IntSerializer,
    ListTupleSerializer, NoneSerializer, NumpyScalar, NumpySerializer, StrSerializer,
    StrSubclassSerializer, Time, UUID, ZeroListSerializer,
};
use crate::serialize::state::SerializerState;
use crate::serialize::writer::{BytesWriter, to_writer, to_writer_pretty};
use core::ptr::NonNull;
use serde::ser::{Serialize, Serializer};

pub(crate) fn serialize(
    ptr: *mut crate::ffi::PyObject,
    default: Option<NonNull<crate::ffi::PyObject>>,
    opts: Opt,
) -> Result<NonNull<crate::ffi::PyObject>, String> {
    let mut buf = BytesWriter::default();
    let obj = PyObjectSerializer::new(ptr, SerializerState::new(opts), default);
    let res = if opt_disabled!(opts, INDENT_2) {
        to_writer(&mut buf, &obj)
    } else {
        to_writer_pretty(&mut buf, &obj)
    };
    match res {
        Ok(()) => Ok(buf.finish(opt_enabled!(opts, APPEND_NEWLINE))),
        Err(err) => {
            buf.abort();
            Err(err.to_string())
        }
    }
}

pub(crate) struct PyObjectSerializer {
    pub ptr: *mut crate::ffi::PyObject,
    pub state: SerializerState,
    pub default: Option<NonNull<crate::ffi::PyObject>>,
}

impl PyObjectSerializer {
    pub fn new(
        ptr: *mut crate::ffi::PyObject,
        state: SerializerState,
        default: Option<NonNull<crate::ffi::PyObject>>,
    ) -> Self {
        PyObjectSerializer {
            ptr: ptr,
            state: state,
            default: default,
        }
    }
}

impl Serialize for PyObjectSerializer {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match pyobject_to_obtype(self.ptr, self.state.opts()) {
            ObType::Str => StrSerializer::new(self.ptr).serialize(serializer),
            ObType::StrSubclass => StrSubclassSerializer::new(self.ptr).serialize(serializer),
            ObType::Int => IntSerializer::new(self.ptr, self.state.opts()).serialize(serializer),
            ObType::None => NoneSerializer::new().serialize(serializer),
            ObType::Float => {
                let val = ffi!(PyFloat_AS_DOUBLE(self.ptr));
                if val.is_nan() || val.is_infinite() {
                    DefaultSerializer::new(self).serialize(serializer)
                } else {
                    FloatSerializer::new(self.ptr, self.state.opts()).serialize(serializer)
                }
            }
            ObType::Bool => BoolSerializer::new(self.ptr).serialize(serializer),
            ObType::Datetime => DateTime::new(self.ptr, self.state.opts()).serialize(serializer),
            ObType::Date => Date::new(self.ptr).serialize(serializer),
            ObType::Time => Time::new(self.ptr, self.state.opts()).serialize(serializer),
            ObType::Uuid => UUID::new(self.ptr).serialize(serializer),
            ObType::Dict => {
                DictGenericSerializer::new(self.ptr, self.state, self.default).serialize(serializer)
            }
            ObType::List => {
                if ffi!(Py_SIZE(self.ptr)) == 0 {
                    ZeroListSerializer::new().serialize(serializer)
                } else {
                    ListTupleSerializer::from_list(self.ptr, self.state, self.default)
                        .serialize(serializer)
                }
            }
            ObType::Tuple => {
                if ffi!(Py_SIZE(self.ptr)) == 0 {
                    ZeroListSerializer::new().serialize(serializer)
                } else {
                    ListTupleSerializer::from_tuple(self.ptr, self.state, self.default)
                        .serialize(serializer)
                }
            }
            ObType::Dataclass => DataclassGenericSerializer::new(self).serialize(serializer),
            ObType::Enum => EnumSerializer::new(self).serialize(serializer),
            ObType::NumpyArray => NumpySerializer::new(self).serialize(serializer),
            ObType::NumpyScalar => {
                NumpyScalar::new(self.ptr, self.state.opts()).serialize(serializer)
            }
            ObType::Fragment => FragmentSerializer::new(self.ptr).serialize(serializer),
            ObType::Unknown => DefaultSerializer::new(self).serialize(serializer),
        }
    }
}
