// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2024-2026)

#[allow(clippy::enum_variant_names)]
#[allow(unused)]
pub(crate) enum PyMemoryViewRefError {
    NotType,
    NotCContiguous,
    NotSupported,
}

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyMemoryViewRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyMemoryViewRef {}
unsafe impl Sync for PyMemoryViewRef {}

impl PartialEq for PyMemoryViewRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyMemoryViewRef {
    #[cfg(CPython)]
    #[inline]
    pub fn from_ptr(ptr: *mut pyo3_ffi::PyObject) -> Result<Self, PyMemoryViewRefError> {
        unsafe {
            debug_assert!(!ptr.is_null());
            if ob_type!(ptr) == &raw mut crate::ffi::PyMemoryView_Type {
                let membuf = unsafe { crate::ffi::PyMemoryView_GET_BUFFER(ptr) };
                #[allow(clippy::cast_possible_wrap)]
                if unsafe {
                    crate::ffi::PyBuffer_IsContiguous(membuf, b'C' as core::ffi::c_char) == 0
                } {
                    return Err(PyMemoryViewRefError::NotCContiguous);
                }
                Ok(Self {
                    ptr: core::ptr::NonNull::new_unchecked(ptr),
                })
            } else {
                Err(PyMemoryViewRefError::NotType)
            }
        }
    }

    #[cfg(not(CPython))]
    #[inline]
    pub fn from_ptr(ptr: *mut pyo3_ffi::PyObject) -> Result<Self, PyMemoryViewRefError> {
        unsafe {
            debug_assert!(!ptr.is_null());
            if ob_type!(ptr) == &raw mut crate::ffi::PyMemoryView_Type {
                Err(PyMemoryViewRefError::NotSupported)
            } else {
                Err(PyMemoryViewRefError::NotType)
            }
        }
    }

    #[allow(unused)]
    #[inline]
    pub fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    #[allow(unused)]
    #[inline]
    pub fn as_non_null_ptr(&self) -> core::ptr::NonNull<pyo3_ffi::PyObject> {
        self.ptr
    }

    #[cfg(CPython)]
    #[inline]
    pub fn as_bytes(&self) -> &'static [u8] {
        unsafe {
            let membuf = crate::ffi::PyMemoryView_GET_BUFFER(self.as_ptr());
            core::slice::from_raw_parts(
                (*membuf).buf.cast::<u8>().cast_const(),
                crate::util::isize_to_usize((*membuf).len),
            )
        }
    }

    #[cfg(CPython)]
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

    #[cfg(not(CPython))]
    #[inline]
    pub fn as_str(&self) -> Option<&'static str> {
        None
    }
}
