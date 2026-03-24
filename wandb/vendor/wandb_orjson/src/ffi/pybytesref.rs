// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

pub(crate) enum PyBytesRefError {
    NotType,
}

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyBytesRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyBytesRef {}
unsafe impl Sync for PyBytesRef {}

impl PartialEq for PyBytesRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyBytesRef {
    #[inline]
    pub fn from_ptr(ptr: *mut pyo3_ffi::PyObject) -> Result<Self, PyBytesRefError> {
        unsafe {
            debug_assert!(!ptr.is_null());
            if ob_type!(ptr) == crate::typeref::BYTES_TYPE {
                Ok(Self {
                    ptr: core::ptr::NonNull::new_unchecked(ptr),
                })
            } else {
                Err(PyBytesRefError::NotType)
            }
        }
    }

    #[inline]
    pub fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    #[allow(unused)]
    #[inline]
    pub fn as_non_null_ptr(&self) -> core::ptr::NonNull<pyo3_ffi::PyObject> {
        self.ptr
    }

    #[inline]
    pub fn as_bytes(&self) -> &'static [u8] {
        unsafe {
            core::slice::from_raw_parts(
                crate::ffi::PyBytes_AS_STRING(self.as_ptr()).cast::<u8>(),
                crate::util::isize_to_usize(crate::ffi::PyBytes_GET_SIZE(self.as_ptr())),
            )
        }
    }

    #[inline]
    pub fn as_str(&self) -> Option<&'static str> {
        let buffer = self.as_bytes();
        if !crate::ffi::utf8::is_valid_utf8(buffer) {
            cold_path!();
            None
        } else {
            unsafe { Some(core::str::from_utf8_unchecked(buffer)) }
        }
    }
}
