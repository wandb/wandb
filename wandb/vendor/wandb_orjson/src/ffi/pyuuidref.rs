// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

use core::ffi::c_uchar;

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyUuidRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyUuidRef {}
unsafe impl Sync for PyUuidRef {}

impl PartialEq for PyUuidRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyUuidRef {
    #[inline]
    pub(crate) unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(ob_type!(ptr) == crate::typeref::UUID_TYPE);
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline(never)]
    pub(crate) fn value(&self) -> u128 {
        unsafe {
            {
                // test_uuid_immutable, test_uuid_int
                let py_int =
                    crate::ffi::PyObject_GetAttr(self.ptr.as_ptr(), crate::typeref::INT_ATTR_STR);
                ffi!(Py_DECREF(py_int));
                let mut buffer: [c_uchar; 16] = [0; 16];
                unsafe {
                    // test_uuid_overflow
                    crate::ffi::PyLong_AsByteArray(
                        py_int.cast::<crate::ffi::PyLongObject>(),
                        buffer.as_mut_ptr(),
                        16,
                        1, // little_endian
                        0, // is_signed
                    );
                };
                u128::from_le_bytes(buffer)
            }
        }
    }
}
