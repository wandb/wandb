// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyTupleRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyTupleRef {}
unsafe impl Sync for PyTupleRef {}

impl PartialEq for PyTupleRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyTupleRef {
    #[inline]
    pub fn with_capacity(cap: usize) -> Self {
        unsafe {
            let ptr = crate::ffi::PyTuple_New(crate::util::usize_to_isize(cap));
            debug_assert!(!ptr.is_null());
            Self { ptr: nonnull!(ptr) }
        }
    }

    #[inline]
    pub unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(
                is_type!(ob_type!(ptr), crate::typeref::TUPLE_TYPE)
                    || is_subclass_by_flag!(tp_flags!(ob_type!(ptr)), Py_TPFLAGS_TUPLE_SUBCLASS)
            );
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

    pub fn get(&self, i: usize) -> *mut pyo3_ffi::PyObject {
        unsafe { crate::ffi::PyTuple_GET_ITEM(self.ptr.as_ptr(), crate::util::usize_to_isize(i)) }
    }

    #[inline]
    pub fn set(&mut self, i: usize, val: *mut pyo3_ffi::PyObject) {
        unsafe {
            crate::ffi::PyTuple_SET_ITEM(self.as_ptr(), crate::util::usize_to_isize(i), val);
        }
    }

    #[inline]
    pub fn len(&self) -> usize {
        unsafe { crate::util::isize_to_usize(super::Py_SIZE(self.ptr.as_ptr())) }
    }
}
