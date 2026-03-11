// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

use crate::deserialize::DeserializeError;
#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
use crate::ffi::{PyByteArrayRef, PyMemoryViewRef};
use crate::ffi::{PyBytesRef, PyStrRef};
use crate::util::INVALID_STR;
use std::borrow::Cow;

#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
const INPUT_TYPE_MESSAGE: &str = "Input must be bytes, bytearray, memoryview, or str";

#[cfg(all(CPython, Py_GIL_DISABLED))]
const INPUT_TYPE_MESSAGE: &str = "Input must be bytes or str";

#[cfg(not(CPython))]
const INPUT_TYPE_MESSAGE: &str = "Input must be bytes, bytearray, or str";

#[cfg_attr(not(Py_GIL_DISABLED), repr(transparent))]
pub struct Utf8Buffer {
    buffer: &'static str,
}

impl Utf8Buffer {
    #[cfg(all(CPython, not(Py_GIL_DISABLED)))]
    fn buffer_from_ptr(
        ptr: *mut crate::ffi::PyObject,
    ) -> Result<Option<&'static str>, DeserializeError<'static>> {
        if let Ok(ob) = PyBytesRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else if let Ok(ob) = PyStrRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else if let Ok(ob) = PyByteArrayRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else if let Ok(ob) = PyMemoryViewRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else {
            Err(DeserializeError::invalid(Cow::Borrowed(INPUT_TYPE_MESSAGE)))
        }
    }

    #[cfg(any(not(CPython), Py_GIL_DISABLED))]
    fn buffer_from_ptr(
        ptr: *mut crate::ffi::PyObject,
    ) -> Result<Option<&'static str>, DeserializeError<'static>> {
        if let Ok(ob) = PyBytesRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else if let Ok(ob) = PyStrRef::from_ptr(ptr) {
            Ok(ob.as_str())
        } else {
            Err(DeserializeError::invalid(Cow::Borrowed(INPUT_TYPE_MESSAGE)))
        }
    }

    pub fn from_pyobject(
        ptr: *mut crate::ffi::PyObject,
    ) -> Result<Self, DeserializeError<'static>> {
        debug_assert!(!ptr.is_null());
        match Utf8Buffer::buffer_from_ptr(ptr) {
            Ok(Some(as_str)) => {
                if as_str.is_empty() {
                    cold_path!();
                    Err(DeserializeError::invalid(Cow::Borrowed(
                        "Input is a zero-length, empty document",
                    )))
                } else {
                    Ok(Self { buffer: as_str })
                }
            }
            Ok(None) => {
                cold_path!();
                Err(DeserializeError::invalid(Cow::Borrowed(INVALID_STR)))
            }
            Err(_) => Err(DeserializeError::invalid(Cow::Borrowed(INPUT_TYPE_MESSAGE))),
        }
    }

    pub fn as_str(&self) -> &'static str {
        self.buffer
    }

    pub fn as_bytes(&self) -> &'static [u8] {
        self.buffer.as_bytes()
    }

    pub fn len(&self) -> usize {
        self.buffer.len()
    }
}
