// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2023-2025)

use crate::ffi::{PyASCIIObject, PyCompactUnicodeObject, PyObject};
use crate::util::usize_to_isize;

macro_rules! validate_str {
    ($ptr:expr) => {
        #[cfg(CPython)]
        unsafe {
            debug_assert!(pyo3_ffi::_PyUnicode_CheckConsistency($ptr.cast::<PyObject>(), 1) == 1)
        };
    };
}

#[inline(never)]
pub(crate) fn pyunicode_ascii(buf: *const u8, num_chars: usize) -> *mut PyObject {
    unsafe {
        let ptr = ffi!(PyUnicode_New(usize_to_isize(num_chars), 127));
        let data_ptr = ptr.cast::<PyASCIIObject>().offset(1).cast::<u8>();
        core::ptr::copy_nonoverlapping(buf, data_ptr, num_chars);
        core::ptr::write(data_ptr.add(num_chars), 0);
        validate_str!(ptr);
        ptr.cast::<PyObject>()
    }
}

#[cold]
#[inline(never)]
pub(crate) fn pyunicode_onebyte(buf: &str, num_chars: usize) -> *mut PyObject {
    unsafe {
        let ptr = ffi!(PyUnicode_New(usize_to_isize(num_chars), 255));
        let mut data_ptr = ptr.cast::<PyCompactUnicodeObject>().offset(1).cast::<u8>();
        for each in buf.chars().fuse() {
            core::ptr::write(data_ptr, each as u8);
            data_ptr = data_ptr.offset(1);
        }
        core::ptr::write(data_ptr, 0);
        validate_str!(ptr);
        ptr.cast::<PyObject>()
    }
}

#[inline(never)]
pub(crate) fn pyunicode_twobyte(buf: &str, num_chars: usize) -> *mut PyObject {
    unsafe {
        let ptr = ffi!(PyUnicode_New(usize_to_isize(num_chars), 65535));
        let mut data_ptr = ptr.cast::<PyCompactUnicodeObject>().offset(1).cast::<u16>();
        for each in buf.chars().fuse() {
            core::ptr::write(data_ptr, each as u16);
            data_ptr = data_ptr.offset(1);
        }
        core::ptr::write(data_ptr, 0);
        validate_str!(ptr);
        ptr.cast::<PyObject>()
    }
}

#[inline(never)]
pub(crate) fn pyunicode_fourbyte(buf: &str, num_chars: usize) -> *mut PyObject {
    unsafe {
        let ptr = ffi!(PyUnicode_New(usize_to_isize(num_chars), 1114111));
        let mut data_ptr = ptr.cast::<PyCompactUnicodeObject>().offset(1).cast::<u32>();
        for each in buf.chars().fuse() {
            core::ptr::write(data_ptr, each as u32);
            data_ptr = data_ptr.offset(1);
        }
        core::ptr::write(data_ptr, 0);
        validate_str!(ptr);
        ptr.cast::<PyObject>()
    }
}
