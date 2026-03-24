// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyBoolRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyBoolRef {}
unsafe impl Sync for PyBoolRef {}

impl PartialEq for PyBoolRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyBoolRef {
    #[inline]
    pub(crate) unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(ob_type!(ptr) == crate::typeref::BOOL_TYPE);
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    #[allow(unused)]
    pub const fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    #[inline]
    #[allow(unused)]
    pub const fn as_non_null_ptr(&self) -> core::ptr::NonNull<pyo3_ffi::PyObject> {
        self.ptr
    }

    #[inline]
    pub fn pytrue() -> Self {
        Self {
            ptr: unsafe { core::ptr::NonNull::new_unchecked(use_immortal!(crate::typeref::TRUE)) },
        }
    }

    #[inline]
    pub fn pyfalse() -> Self {
        Self {
            ptr: unsafe { core::ptr::NonNull::new_unchecked(use_immortal!(crate::typeref::FALSE)) },
        }
    }
}
