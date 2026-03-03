// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2026), Jack Amadeo (2023)

use core::ptr::null_mut;

use crate::deserialize::DeserializeError;
use crate::ffi::{Py_DECREF, PyErr_SetObject, PyIntRef, PyObject, PyStrRef, PyTupleRef};
use crate::typeref::{JsonDecodeError, JsonEncodeError};

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) fn raise_loads_exception(err: DeserializeError) -> *mut PyObject {
    unsafe {
        let err_pos = PyIntRef::from_i64(err.pos());
        let err_msg = PyStrRef::from_str(&err.message);
        let doc = match err.data {
            Some(as_str) => PyStrRef::from_str(as_str),
            None => PyStrRef::empty(),
        };
        let mut args = PyTupleRef::with_capacity(3);
        args.set(0, err_msg.as_ptr());
        args.set(1, doc.as_ptr());
        args.set(2, err_pos.as_ptr());
        PyErr_SetObject(JsonDecodeError, args.as_ptr());
        Py_DECREF(args.as_ptr());
    }
    null_mut()
}

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) fn raise_dumps_exception_fixed(msg: &str) -> *mut PyObject {
    unsafe {
        let err_msg = PyStrRef::from_str(msg);
        PyErr_SetObject(JsonEncodeError, err_msg.as_ptr());
        Py_DECREF(err_msg.as_ptr());
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

        let err_msg = PyStrRef::from_str(err);
        PyErr_SetObject(JsonEncodeError, err_msg.as_ptr());
        Py_DECREF(err_msg.as_ptr());

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

        let err_msg = PyStrRef::from_str(err);
        PyErr_SetObject(JsonEncodeError, err_msg.as_ptr());
        Py_DECREF(err_msg.as_ptr());

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
