// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025)

use core::ffi::c_char;

use core::ptr::null_mut;
use pyo3_ffi::{
    Py_DECREF, Py_INCREF, Py_SIZE, Py_TPFLAGS_DEFAULT, PyErr_SetObject, PyExc_TypeError, PyObject,
    PyType_Ready, PyType_Type, PyTypeObject, PyUnicode_FromStringAndSize, PyVarObject,
};

#[cfg(Py_GIL_DISABLED)]
use super::atomiculong::AtomicCULong;
#[cfg(Py_GIL_DISABLED)]
use core::sync::atomic::{AtomicIsize, AtomicU32};

#[cfg(Py_GIL_DISABLED)]
macro_rules! pymutex_new {
    () => {
        unsafe { core::mem::zeroed() }
    };
}

#[repr(C)]
pub(crate) struct Fragment {
    #[cfg(Py_GIL_DISABLED)]
    pub ob_tid: usize,
    #[cfg(all(Py_GIL_DISABLED, Py_3_14))]
    pub ob_flags: u16,
    #[cfg(all(Py_GIL_DISABLED, not(Py_3_14)))]
    pub _padding: u16,
    #[cfg(Py_GIL_DISABLED)]
    pub ob_mutex: pyo3_ffi::PyMutex,
    #[cfg(Py_GIL_DISABLED)]
    pub ob_gc_bits: u8,
    #[cfg(Py_GIL_DISABLED)]
    pub ob_ref_local: AtomicU32,
    #[cfg(Py_GIL_DISABLED)]
    pub ob_ref_shared: AtomicIsize,
    #[cfg(not(Py_GIL_DISABLED))]
    pub ob_refcnt: pyo3_ffi::Py_ssize_t,
    #[cfg(PyPy)]
    pub ob_pypy_link: pyo3_ffi::Py_ssize_t,
    pub ob_type: *mut pyo3_ffi::PyTypeObject,
    pub contents: *mut pyo3_ffi::PyObject,
}

#[cold]
#[inline(never)]
#[cfg_attr(feature = "optimize", optimize(size))]
fn raise_args_exception() {
    unsafe {
        let msg = "orjson.Fragment() takes exactly 1 positional argument";
        let err_msg =
            PyUnicode_FromStringAndSize(msg.as_ptr().cast::<c_char>(), msg.len() as isize);
        PyErr_SetObject(PyExc_TypeError, err_msg);
        Py_DECREF(err_msg);
    };
}

#[unsafe(no_mangle)]
#[cold]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) unsafe extern "C" fn orjson_fragment_tp_new(
    _subtype: *mut PyTypeObject,
    args: *mut PyObject,
    kwds: *mut PyObject,
) -> *mut PyObject {
    unsafe {
        if Py_SIZE(args) != 1 || !kwds.is_null() {
            raise_args_exception();
            null_mut()
        } else {
            let contents = crate::ffi::PyTuple_GET_ITEM(args, 0);
            Py_INCREF(contents);
            let obj = Box::new(Fragment {
                #[cfg(Py_GIL_DISABLED)]
                ob_tid: 0,
                #[cfg(all(Py_GIL_DISABLED, Py_3_14))]
                ob_flags: 0,
                #[cfg(all(Py_GIL_DISABLED, not(Py_3_14)))]
                _padding: 0,
                #[cfg(Py_GIL_DISABLED)]
                ob_mutex: pymutex_new!(),
                #[cfg(Py_GIL_DISABLED)]
                ob_gc_bits: 0,
                #[cfg(Py_GIL_DISABLED)]
                ob_ref_local: AtomicU32::new(0),
                #[cfg(Py_GIL_DISABLED)]
                ob_ref_shared: AtomicIsize::new(0),
                #[cfg(not(Py_GIL_DISABLED))]
                ob_refcnt: 1,
                #[cfg(PyPy)]
                ob_pypy_link: 0,
                ob_type: crate::typeref::FRAGMENT_TYPE,
                contents: contents,
            });
            Box::into_raw(obj).cast::<PyObject>()
        }
    }
}

#[unsafe(no_mangle)]
#[cold]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) unsafe extern "C" fn orjson_fragment_dealloc(object: *mut PyObject) {
    unsafe {
        Py_DECREF((*object.cast::<Fragment>()).contents);
        crate::ffi::PyMem_Free(object.cast::<core::ffi::c_void>());
    }
}

#[unsafe(no_mangle)]
#[cold]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) unsafe extern "C" fn orjson_fragmenttype_new() -> *mut PyTypeObject {
    unsafe {
        #[cfg(Py_GIL_DISABLED)]
        let tp_flags: AtomicCULong =
            AtomicCULong::new(Py_TPFLAGS_DEFAULT | pyo3_ffi::Py_TPFLAGS_IMMUTABLETYPE);
        #[cfg(all(Py_3_10, not(Py_GIL_DISABLED)))]
        let tp_flags: core::ffi::c_ulong = Py_TPFLAGS_DEFAULT | pyo3_ffi::Py_TPFLAGS_IMMUTABLETYPE;
        #[cfg(not(Py_3_10))]
        let tp_flags: core::ffi::c_ulong = Py_TPFLAGS_DEFAULT;
        let ob = Box::new(PyTypeObject {
            ob_base: PyVarObject {
                ob_base: PyObject {
                    #[cfg(Py_GIL_DISABLED)]
                    ob_tid: 0,
                    #[cfg(all(Py_GIL_DISABLED, Py_3_14))]
                    ob_flags: 0,
                    #[cfg(all(Py_GIL_DISABLED, not(Py_3_14)))]
                    _padding: 0,
                    #[cfg(Py_GIL_DISABLED)]
                    ob_mutex: pymutex_new!(),
                    #[cfg(Py_GIL_DISABLED)]
                    ob_gc_bits: 0,
                    #[cfg(Py_GIL_DISABLED)]
                    ob_ref_local: AtomicU32::new(crate::ffi::compat::_Py_IMMORTAL_REFCNT_LOCAL),
                    #[cfg(Py_GIL_DISABLED)]
                    ob_ref_shared: AtomicIsize::new(0),
                    #[cfg(all(Py_3_12, not(Py_GIL_DISABLED)))]
                    ob_refcnt: pyo3_ffi::PyObjectObRefcnt { ob_refcnt: 0 },
                    #[cfg(not(Py_3_12))]
                    ob_refcnt: 0,
                    #[cfg(PyPy)]
                    ob_pypy_link: 0,
                    ob_type: &raw mut PyType_Type,
                },
                #[cfg(not(GraalPy))]
                ob_size: 0,
                #[cfg(GraalPy)]
                _ob_size_graalpy: 0,
            },
            tp_name: c"orjson.Fragment".as_ptr(),
            tp_basicsize: core::mem::size_of::<Fragment>() as isize,
            tp_itemsize: 0,
            tp_dealloc: Some(orjson_fragment_dealloc),
            tp_init: None,
            tp_new: Some(orjson_fragment_tp_new),
            tp_flags: tp_flags,
            // ...
            tp_bases: null_mut(),
            tp_cache: null_mut(),
            tp_del: None,
            tp_finalize: None,
            tp_free: None,
            tp_is_gc: None,
            tp_mro: null_mut(),
            tp_subclasses: null_mut(),
            tp_vectorcall: None,
            tp_version_tag: 0,
            tp_weaklist: null_mut(),
            tp_vectorcall_offset: 0,
            tp_getattr: None,
            tp_setattr: None,
            tp_as_async: null_mut(),
            tp_repr: None,
            tp_as_number: null_mut(),
            tp_as_sequence: null_mut(),
            tp_as_mapping: null_mut(),
            tp_hash: None,
            tp_call: None,
            tp_str: None,
            tp_getattro: None,
            tp_setattro: None,
            tp_as_buffer: null_mut(),
            tp_doc: core::ptr::null_mut(),
            tp_traverse: None,
            tp_clear: None,
            tp_richcompare: None,
            tp_weaklistoffset: 0,
            tp_iter: None,
            tp_iternext: None,
            tp_methods: null_mut(),
            tp_members: null_mut(),
            tp_getset: null_mut(),
            tp_base: null_mut(),
            tp_dict: null_mut(),
            tp_descr_get: None,
            tp_descr_set: None,
            tp_dictoffset: 0,
            tp_alloc: None,
            #[cfg(Py_3_12)]
            tp_watched: 0,
        });
        let ob_ptr = Box::into_raw(ob);
        PyType_Ready(ob_ptr);
        ob_ptr
    }
}
