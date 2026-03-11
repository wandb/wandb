// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2022-2026)

#[cfg(Py_GIL_DISABLED)]
mod atomiculong;
#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
mod buffer;
mod bytes;
pub(crate) mod compat;
mod fragment;
mod pyboolref;
#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
mod pybytearrayref;
mod pybytesref;
mod pydictref;
mod pyfloatref;
mod pyfragmentref;
mod pyintref;
mod pylistref;
#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
mod pymemoryview;
mod pynoneref;
mod pystrref;
mod pytupleref;
mod pyuuidref;
mod utf8;

pub(crate) use compat::*;

#[allow(unused_imports)]
pub(crate) use {
    bytes::{PyBytes_AS_STRING, PyBytes_GET_SIZE, PyBytesObject},
    fragment::{Fragment, orjson_fragmenttype_new},
    pyboolref::PyBoolRef,
    pybytesref::{PyBytesRef, PyBytesRefError},
    pydictref::PyDictRef,
    pyfloatref::PyFloatRef,
    pyfragmentref::{PyFragmentRef, PyFragmentRefError},
    pyintref::{PyIntError, PyIntKind, PyIntRef},
    pylistref::PyListRef,
    pynoneref::PyNoneRef,
    pystrref::{PyStrRef, PyStrSubclassRef, set_str_create_fn},
    pytupleref::PyTupleRef,
    pyuuidref::PyUuidRef,
};

#[allow(unused_imports)]
#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
pub(crate) use {
    pybytearrayref::{PyByteArrayRef, PyByteArrayRefError},
    pymemoryview::{PyMemoryViewRef, PyMemoryViewRefError},
};

#[allow(unused_imports)]
pub(crate) use pyo3_ffi::{
    METH_FASTCALL, METH_KEYWORDS, METH_O, Py_DECREF, Py_False, Py_INCREF, Py_None, Py_REFCNT,
    Py_TPFLAGS_DEFAULT, Py_TPFLAGS_DICT_SUBCLASS, Py_TPFLAGS_LIST_SUBCLASS,
    Py_TPFLAGS_LONG_SUBCLASS, Py_TPFLAGS_TUPLE_SUBCLASS, Py_TPFLAGS_UNICODE_SUBCLASS, Py_TYPE,
    Py_True, Py_XDECREF, Py_buffer, Py_hash_t, Py_intptr_t, Py_mod_exec, Py_ssize_t, PyASCIIObject,
    PyBool_Type, PyBuffer_IsContiguous, PyByteArray_AsString, PyByteArray_Size, PyByteArray_Type,
    PyBytes_FromStringAndSize, PyBytes_Type, PyCFunction_NewEx, PyCapsule_Import,
    PyCompactUnicodeObject, PyDateTime_CAPI, PyDateTime_DATE_GET_HOUR,
    PyDateTime_DATE_GET_MICROSECOND, PyDateTime_DATE_GET_MINUTE, PyDateTime_DATE_GET_SECOND,
    PyDateTime_DATE_GET_TZINFO, PyDateTime_DELTA_GET_DAYS, PyDateTime_DELTA_GET_SECONDS,
    PyDateTime_DateTime, PyDateTime_GET_DAY, PyDateTime_GET_MONTH, PyDateTime_GET_YEAR,
    PyDateTime_IMPORT, PyDateTime_TIME_GET_HOUR, PyDateTime_TIME_GET_MICROSECOND,
    PyDateTime_TIME_GET_MINUTE, PyDateTime_TIME_GET_SECOND, PyDateTime_Time, PyDict_Contains,
    PyDict_Next, PyDict_SetItem, PyDict_Type, PyDictObject, PyErr_Clear, PyErr_NewException,
    PyErr_Occurred, PyErr_SetObject, PyExc_TypeError, PyException_SetCause, PyFloat_AS_DOUBLE,
    PyFloat_FromDouble, PyFloat_Type, PyImport_ImportModule, PyList_GET_ITEM, PyList_New,
    PyList_SET_ITEM, PyList_Type, PyListObject, PyLong_AsLong, PyLong_AsLongLong,
    PyLong_AsUnsignedLongLong, PyLong_FromLongLong, PyLong_FromUnsignedLongLong, PyLong_Type,
    PyLongObject, PyMapping_GetItemString, PyMem_Free, PyMem_Malloc, PyMem_Realloc,
    PyMemoryView_Type, PyMethodDef, PyMethodDefPointer, PyModule_AddIntConstant,
    PyModule_AddObject, PyModuleDef, PyModuleDef_HEAD_INIT, PyModuleDef_Init, PyModuleDef_Slot,
    PyObject, PyObject_CallFunctionObjArgs, PyObject_CallMethodObjArgs, PyObject_GenericGetDict,
    PyObject_GetAttr, PyObject_HasAttr, PyObject_Hash, PyObject_Vectorcall, PyTuple_New,
    PyTuple_Type, PyTupleObject, PyType_Ready, PyType_Type, PyTypeObject, PyUnicode_AsUTF8AndSize,
    PyUnicode_FromStringAndSize, PyUnicode_InternFromString, PyUnicode_New, PyUnicode_Type,
    PyVarObject, PyVectorcall_NARGS,
};

#[allow(unused_imports, deprecated)]
pub(crate) use pyo3_ffi::PyErr_Restore;

#[cfg(CPython)]
pub(crate) use pyo3_ffi::{PyObject_CallMethodNoArgs, PyObject_CallMethodOneArg};

#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
pub(crate) use buffer::PyMemoryView_GET_BUFFER;

#[cfg(not(feature = "inline_str"))]
pub(crate) use pyo3_ffi::{PyUnicode_DATA, PyUnicode_KIND};

#[cfg(Py_3_12)]
#[allow(unused_imports)]
pub(crate) use pyo3_ffi::{
    Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED, Py_mod_multiple_interpreters,
    PyErr_GetRaisedException, PyErr_SetRaisedException, PyType_GetDict,
};

#[cfg(not(Py_3_12))]
#[allow(unused_imports)]
pub(crate) use pyo3_ffi::{PyErr_Fetch, PyErr_NormalizeException};

#[cfg(not(Py_3_13))]
#[allow(unused_imports)]
pub(crate) use pyo3_ffi::PyModule_AddObjectRef;

#[cfg(Py_3_13)]
#[allow(unused_imports)]
pub(crate) use pyo3_ffi::PyModule_Add;

#[cfg(Py_3_13)]
#[allow(unused_imports)]
pub(crate) use pyo3_ffi::{Py_MOD_GIL_USED, Py_mod_gil};
