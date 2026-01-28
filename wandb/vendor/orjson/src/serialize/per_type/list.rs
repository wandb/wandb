// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::serialize::error::SerializeError;
use crate::serialize::obtype::{ObType, pyobject_to_obtype};
use crate::serialize::per_type::{
    BoolSerializer, DataclassGenericSerializer, Date, DateTime, DefaultSerializer,
    DictGenericSerializer, EnumSerializer, FloatSerializer, FragmentSerializer, IntSerializer,
    NoneSerializer, NumpyScalar, NumpySerializer, StrSerializer, StrSubclassSerializer, Time, UUID,
};
use crate::serialize::serializer::PyObjectSerializer;
use crate::serialize::state::SerializerState;
use crate::typeref::{LIST_TYPE, TUPLE_TYPE};
use crate::util::isize_to_usize;

use core::ptr::NonNull;
use serde::ser::{Serialize, SerializeSeq, Serializer};

pub(crate) struct ZeroListSerializer;

impl ZeroListSerializer {
    pub const fn new() -> Self {
        Self {}
    }
}

impl Serialize for ZeroListSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_bytes(b"[]")
    }
}

pub(crate) struct ListTupleSerializer {
    data_ptr: *const *mut crate::ffi::PyObject,
    state: SerializerState,
    default: Option<NonNull<crate::ffi::PyObject>>,
    len: usize,
}

impl ListTupleSerializer {
    pub fn from_list(
        ptr: *mut crate::ffi::PyObject,
        state: SerializerState,
        default: Option<NonNull<crate::ffi::PyObject>>,
    ) -> Self {
        debug_assert!(
            is_type!(ob_type!(ptr), LIST_TYPE)
                || is_subclass_by_flag!(tp_flags!(ob_type!(ptr)), Py_TPFLAGS_LIST_SUBCLASS)
        );
        let data_ptr = unsafe { (*ptr.cast::<crate::ffi::PyListObject>()).ob_item };
        let len = isize_to_usize(ffi!(Py_SIZE(ptr)));
        Self {
            data_ptr: data_ptr,
            len: len,
            state: state.copy_for_recursive_call(),
            default: default,
        }
    }

    pub fn from_tuple(
        ptr: *mut crate::ffi::PyObject,
        state: SerializerState,
        default: Option<NonNull<crate::ffi::PyObject>>,
    ) -> Self {
        debug_assert!(
            is_type!(ob_type!(ptr), TUPLE_TYPE)
                || is_subclass_by_flag!(tp_flags!(ob_type!(ptr)), Py_TPFLAGS_TUPLE_SUBCLASS)
        );
        let data_ptr = unsafe { (*ptr.cast::<crate::ffi::PyTupleObject>()).ob_item.as_ptr() };
        let len = isize_to_usize(ffi!(Py_SIZE(ptr)));
        Self {
            data_ptr: data_ptr,
            len: len,
            state: state.copy_for_recursive_call(),
            default: default,
        }
    }
}

impl Serialize for ListTupleSerializer {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.state.recursion_limit() {
            cold_path!();
            err!(SerializeError::RecursionLimit)
        }
        debug_assert!(self.len >= 1);
        let mut seq = serializer.serialize_seq(None).unwrap();
        for idx in 0..self.len {
            let value = unsafe { *((self.data_ptr).add(idx)) };
            match pyobject_to_obtype(value, self.state.opts()) {
                ObType::Str => {
                    seq.serialize_element(&StrSerializer::new(value))?;
                }
                ObType::StrSubclass => {
                    seq.serialize_element(&StrSubclassSerializer::new(value))?;
                }
                ObType::Int => {
                    seq.serialize_element(&IntSerializer::new(value, self.state.opts()))?;
                }
                ObType::None => {
                    seq.serialize_element(&NoneSerializer::new()).unwrap();
                }
                ObType::Float => {
                    seq.serialize_element(&FloatSerializer::new(value, self.state.opts()))?;
                }
                ObType::Bool => {
                    seq.serialize_element(&BoolSerializer::new(value)).unwrap();
                }
                ObType::Datetime => {
                    seq.serialize_element(&DateTime::new(value, self.state.opts()))?;
                }
                ObType::Date => {
                    seq.serialize_element(&Date::new(value))?;
                }
                ObType::Time => {
                    seq.serialize_element(&Time::new(value, self.state.opts()))?;
                }
                ObType::Uuid => {
                    seq.serialize_element(&UUID::new(value)).unwrap();
                }
                ObType::Dict => {
                    let pyvalue = DictGenericSerializer::new(value, self.state, self.default);
                    seq.serialize_element(&pyvalue)?;
                }
                ObType::List => {
                    if ffi!(Py_SIZE(value)) == 0 {
                        seq.serialize_element(&ZeroListSerializer::new()).unwrap();
                    } else {
                        let pyvalue =
                            ListTupleSerializer::from_list(value, self.state, self.default);
                        seq.serialize_element(&pyvalue)?;
                    }
                }
                ObType::Tuple => {
                    if ffi!(Py_SIZE(value)) == 0 {
                        seq.serialize_element(&ZeroListSerializer::new()).unwrap();
                    } else {
                        let pyvalue =
                            ListTupleSerializer::from_tuple(value, self.state, self.default);
                        seq.serialize_element(&pyvalue)?;
                    }
                }
                ObType::Dataclass => {
                    seq.serialize_element(&DataclassGenericSerializer::new(
                        &PyObjectSerializer::new(value, self.state, self.default),
                    ))?;
                }
                ObType::Enum => {
                    seq.serialize_element(&EnumSerializer::new(&PyObjectSerializer::new(
                        value,
                        self.state,
                        self.default,
                    )))?;
                }
                ObType::NumpyArray => {
                    seq.serialize_element(&NumpySerializer::new(&PyObjectSerializer::new(
                        value,
                        self.state,
                        self.default,
                    )))?;
                }
                ObType::NumpyScalar => {
                    seq.serialize_element(&NumpyScalar::new(value, self.state.opts()))?;
                }
                ObType::Fragment => {
                    seq.serialize_element(&FragmentSerializer::new(value))?;
                }
                ObType::Unknown => {
                    seq.serialize_element(&DefaultSerializer::new(&PyObjectSerializer::new(
                        value,
                        self.state,
                        self.default,
                    )))?;
                }
            }
        }
        seq.end()
    }
}
