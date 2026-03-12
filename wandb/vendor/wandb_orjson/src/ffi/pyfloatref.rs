// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyFloatRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyFloatRef {}
unsafe impl Sync for PyFloatRef {}

impl PartialEq for PyFloatRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyFloatRef {
    #[inline]
    pub(crate) unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(ob_type!(ptr) == crate::typeref::FLOAT_TYPE);
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    pub fn as_non_null_ptr(&self) -> core::ptr::NonNull<pyo3_ffi::PyObject> {
        self.ptr
    }

    #[inline]
    pub fn value(&self) -> f64 {
        unsafe { super::PyFloat_AS_DOUBLE(self.ptr.as_ptr()) }
    }

    #[inline]
    pub fn from_f64(value: f64) -> Self {
        unsafe {
            let ptr = super::PyFloat_FromDouble(value);
            Self::from_ptr_unchecked(ptr)
        }
    }
}
