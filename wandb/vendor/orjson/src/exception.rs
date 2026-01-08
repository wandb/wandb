// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025), Jack Amadeo (2023)

use core::ffi::c_char;
use core::ptr::null_mut;

use crate::deserialize::DeserializeError;
use crate::ffi::{
    Py_DECREF, PyErr_SetObject, PyLong_FromLongLong, PyObject, PyTuple_New,
    PyUnicode_FromStringAndSize,
};
use crate::typeref::{EMPTY_UNICODE, JsonDecodeError, JsonEncodeError};
use crate::util::usize_to_isize;

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) fn raise_loads_exception(err: DeserializeError) -> *mut PyObject {
    unsafe {
        let err_pos = err.pos();
        let msg = err.message;
        let doc = match err.data {
            Some(as_str) => PyUnicode_FromStringAndSize(
                as_str.as_ptr().cast::<c_char>(),
                usize_to_isize(as_str.len()),
            ),
            None => {
                use_immortal!(EMPTY_UNICODE)
            }
        };
        let err_msg =
            PyUnicode_FromStringAndSize(msg.as_ptr().cast::<c_char>(), usize_to_isize(msg.len()));
        let args = PyTuple_New(3);
        let pos = PyLong_FromLongLong(err_pos);
        crate::ffi::PyTuple_SET_ITEM(args, 0, err_msg);
        crate::ffi::PyTuple_SET_ITEM(args, 1, doc);
        crate::ffi::PyTuple_SET_ITEM(args, 2, pos);
        PyErr_SetObject(JsonDecodeError, args);
        Py_DECREF(args);
    }
    null_mut()
}

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) fn raise_dumps_exception_fixed(msg: &str) -> *mut PyObject {
    unsafe {
        let err_msg =
            PyUnicode_FromStringAndSize(msg.as_ptr().cast::<c_char>(), usize_to_isize(msg.len()));
        PyErr_SetObject(JsonEncodeError, err_msg);
        debug_assert!(ffi!(Py_REFCNT(err_msg)) <= 2);
        Py_DECREF(err_msg);
    }
    null_mut()
}

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
#[cfg(Py_3_12)]
pub(crate) fn raise_dumps_exception_dynamic(err: &str) -> *mut PyObject {
    unsafe {
        let cause_exc: *mut PyObject = crate::ffi::PyErr_GetRaisedException();

        let err_msg =
            PyUnicode_FromStringAndSize(err.as_ptr().cast::<c_char>(), usize_to_isize(err.len()));
        PyErr_SetObject(JsonEncodeError, err_msg);
        debug_assert!(ffi!(Py_REFCNT(err_msg)) <= 2);
        Py_DECREF(err_msg);

        if !cause_exc.is_null() {
            let exc: *mut PyObject = crate::ffi::PyErr_GetRaisedException();
            crate::ffi::PyException_SetCause(exc, cause_exc);
            crate::ffi::PyErr_SetRaisedException(exc);
        }
    }
    null_mut()
}

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
#[cfg(not(Py_3_12))]
pub(crate) fn raise_dumps_exception_dynamic(err: &str) -> *mut PyObject {
    unsafe {
        let mut cause_tp: *mut PyObject = null_mut();
        let mut cause_val: *mut PyObject = null_mut();
        let mut cause_traceback: *mut PyObject = null_mut();
        crate::ffi::PyErr_Fetch(&mut cause_tp, &mut cause_val, &mut cause_traceback);

        let err_msg =
            PyUnicode_FromStringAndSize(err.as_ptr().cast::<c_char>(), usize_to_isize(err.len()));
        PyErr_SetObject(JsonEncodeError, err_msg);
        debug_assert!(ffi!(Py_REFCNT(err_msg)) == 2);
        Py_DECREF(err_msg);
        let mut tp: *mut PyObject = null_mut();
        let mut val: *mut PyObject = null_mut();
        let mut traceback: *mut PyObject = null_mut();
        crate::ffi::PyErr_Fetch(&mut tp, &mut val, &mut traceback);
        crate::ffi::PyErr_NormalizeException(&mut tp, &mut val, &mut traceback);

        if !cause_tp.is_null() {
            crate::ffi::PyErr_NormalizeException(
                &mut cause_tp,
                &mut cause_val,
                &mut cause_traceback,
            );
            crate::ffi::PyException_SetCause(val, cause_val);
            Py_DECREF(cause_tp);
        }
        if !cause_traceback.is_null() {
            Py_DECREF(cause_traceback);
        }

        crate::ffi::PyErr_Restore(tp, val, traceback);
    }
    null_mut()
}
