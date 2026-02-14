// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2023-2025)

// longintrepr.h, _longobject, _PyLongValue

#[allow(dead_code)]
#[cfg(Py_3_12)]
#[allow(non_upper_case_globals)]
const SIGN_MASK: usize = 3;

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[allow(non_upper_case_globals)]
const SIGN_ZERO: usize = 1;

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[allow(non_upper_case_globals)]
const NON_SIZE_BITS: usize = 3;

#[cfg(Py_3_12)]
#[repr(C)]
pub(crate) struct _PyLongValue {
    pub lv_tag: usize,
    pub ob_digit: u32,
}

#[cfg(Py_3_12)]
#[repr(C)]
pub(crate) struct PyLongObject {
    pub ob_base: pyo3_ffi::PyObject,
    pub long_value: _PyLongValue,
}

#[allow(dead_code)]
#[cfg(not(Py_3_12))]
#[repr(C)]
pub(crate) struct PyLongObject {
    pub ob_base: pyo3_ffi::PyVarObject,
    pub ob_digit: u32,
}

#[cfg(Py_3_12)]
#[inline(always)]
pub(crate) fn pylong_is_unsigned(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { (*ptr.cast::<PyLongObject>()).long_value.lv_tag & SIGN_MASK == 0 }
}

#[cfg(not(Py_3_12))]
#[inline(always)]
pub(crate) fn pylong_is_unsigned(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { super::compat::Py_SIZE(ptr.cast::<pyo3_ffi::PyVarObject>()) > 0 }
}

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_fits_in_i32(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { (*ptr.cast::<PyLongObject>()).long_value.lv_tag < (2 << NON_SIZE_BITS) }
}

#[cfg(all(not(Py_3_12), feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_fits_in_i32(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { isize::abs(super::compat::Py_SIZE(ptr.cast::<pyo3_ffi::PyVarObject>())) == 1 }
}

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_is_zero(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { (*ptr.cast::<PyLongObject>()).long_value.lv_tag & SIGN_MASK == SIGN_ZERO }
}

#[cfg(all(not(Py_3_12), feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_is_zero(ptr: *mut pyo3_ffi::PyObject) -> bool {
    unsafe { super::compat::Py_SIZE(ptr.cast::<pyo3_ffi::PyVarObject>()) == 0 }
}

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_get_inline_value(ptr: *mut pyo3_ffi::PyObject) -> i64 {
    unsafe {
        if pylong_is_unsigned(ptr) {
            i64::from((*ptr.cast::<PyLongObject>()).long_value.ob_digit)
        } else {
            -i64::from((*ptr.cast::<PyLongObject>()).long_value.ob_digit)
        }
    }
}

#[cfg(all(not(Py_3_12), feature = "inline_int"))]
#[inline(always)]
pub(crate) fn pylong_get_inline_value(ptr: *mut pyo3_ffi::PyObject) -> i64 {
    unsafe {
        super::compat::Py_SIZE(ptr.cast::<pyo3_ffi::PyVarObject>()) as i64
            * i64::from(unsafe { (*ptr.cast::<PyLongObject>()).ob_digit })
    }
}
