// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2022-2025)

use crate::ffi::{Py_ssize_t, PyObject};
use core::ffi::c_char;

pub(crate) use pyo3_ffi::PyBytesObject;

#[cfg(CPython)]
#[allow(non_snake_case)]
#[inline(always)]
pub(crate) unsafe fn PyBytes_AS_STRING(op: *mut PyObject) -> *const c_char {
    unsafe { (&raw const (*op.cast::<crate::ffi::PyBytesObject>()).ob_sval).cast::<c_char>() }
}

#[cfg(not(CPython))]
#[allow(non_snake_case)]
#[inline(always)]
pub(crate) unsafe fn PyBytes_AS_STRING(op: *mut PyObject) -> *const c_char {
    unsafe { pyo3_ffi::PyBytes_AsString(op) }
}

#[allow(non_snake_case)]
#[inline(always)]
pub(crate) unsafe fn PyBytes_GET_SIZE(op: *mut PyObject) -> Py_ssize_t {
    unsafe { super::compat::Py_SIZE(op.cast::<crate::ffi::PyVarObject>()) }
}
