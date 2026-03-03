// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

use crate::ffi::{Fragment, PyBytesRef, PyStrRef};

pub(crate) enum PyFragmentRefError {
    InvalidStr,
    InvalidFragment,
}

#[repr(transparent)]
pub(crate) struct PyFragmentRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyFragmentRef {}
unsafe impl Sync for PyFragmentRef {}

impl PartialEq for PyFragmentRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyFragmentRef {
    #[inline]
    pub(crate) unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(ob_type!(ptr) == crate::typeref::FRAGMENT_TYPE);
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    #[allow(unused)]
    pub fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    #[inline]
    #[allow(unused)]
    pub fn as_non_null_ptr(&self) -> core::ptr::NonNull<pyo3_ffi::PyObject> {
        self.ptr
    }

    #[cold]
    pub fn value(&self) -> Result<&[u8], PyFragmentRefError> {
        let buffer: &[u8];
        unsafe {
            let contents: *mut pyo3_ffi::PyObject =
                (*self.ptr.as_ptr().cast::<Fragment>()).contents;
            if let Ok(ob) = PyBytesRef::from_ptr(contents) {
                buffer = ob.as_bytes();
            } else if let Ok(ob) = PyStrRef::from_ptr(contents) {
                match ob.as_str() {
                    Some(ob) => buffer = ob.as_bytes(),
                    None => return Err(PyFragmentRefError::InvalidStr),
                }
            } else {
                return Err(PyFragmentRefError::InvalidFragment);
            }
            Ok(buffer)
        }
    }
}
