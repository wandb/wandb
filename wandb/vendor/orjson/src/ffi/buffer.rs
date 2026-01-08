// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2021-2025), Baul (2020)

use crate::ffi::{Py_buffer, Py_hash_t, Py_ssize_t, PyObject, PyVarObject};
use core::ffi::c_int;

#[cfg(CPython)]
#[repr(C)]
pub(crate) struct _PyManagedBufferObject {
    pub ob_base: *mut PyObject,
    pub flags: c_int,
    pub exports: Py_ssize_t,
    pub master: *mut Py_buffer,
}

#[cfg(CPython)]
#[repr(C)]
pub(crate) struct PyMemoryViewObject {
    pub ob_base: PyVarObject,
    pub mbuf: *mut _PyManagedBufferObject,
    pub hash: Py_hash_t,
    pub flags: c_int,
    pub exports: Py_ssize_t,
    pub view: Py_buffer,
    pub weakreflist: *mut PyObject,
    pub ob_array: [Py_ssize_t; 1],
}

#[cfg(CPython)]
#[allow(non_snake_case)]
#[inline(always)]
pub(crate) unsafe fn PyMemoryView_GET_BUFFER(op: *mut PyObject) -> *const Py_buffer {
    unsafe { &(*op.cast::<PyMemoryViewObject>()).view }
}
