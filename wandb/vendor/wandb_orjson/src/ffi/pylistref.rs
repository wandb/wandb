// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyListRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyListRef {}
unsafe impl Sync for PyListRef {}

impl PartialEq for PyListRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyListRef {
    #[inline]
    pub unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(
                is_type!(ob_type!(ptr), crate::typeref::LIST_TYPE)
                    || is_subclass_by_flag!(tp_flags!(ob_type!(ptr)), Py_TPFLAGS_LIST_SUBCLASS)
            );
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    pub fn with_capacity(cap: usize) -> Self {
        unsafe {
            let list = super::PyList_New(crate::util::usize_to_isize(cap));
            debug_assert!(!list.is_null());
            Self {
                ptr: nonnull!(list),
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

    #[cfg(CPython)]
    #[inline]
    pub fn data_ptr(&self) -> *const *mut pyo3_ffi::PyObject {
        unsafe { (*self.ptr.as_ptr().cast::<pyo3_ffi::PyListObject>()).ob_item }
    }

    #[cfg(CPython)]
    #[inline]
    pub fn get(&mut self, i: usize) -> *mut pyo3_ffi::PyObject {
        unsafe { *((self.data_ptr()).add(i)) }
    }

    #[cfg(not(CPython))]
    #[inline]
    pub fn get(&mut self, i: usize) -> *mut pyo3_ffi::PyObject {
        unsafe { pyo3_ffi::PyList_GetItem(self.ptr.as_ptr(), crate::util::usize_to_isize(i)) }
    }

    #[cfg(CPython)]
    #[inline]
    pub fn set(&mut self, i: usize, val: *mut pyo3_ffi::PyObject) {
        unsafe {
            core::ptr::write(self.data_ptr().cast_mut().add(i), val);
        }
    }

    #[cfg(not(CPython))]
    pub fn set(&mut self, i: usize, val: *mut pyo3_ffi::PyObject) {
        unsafe { pyo3_ffi::PyList_SetItem(self.ptr.as_ptr(), crate::util::usize_to_isize(i), val) };
    }

    #[inline]
    pub fn len(&self) -> usize {
        unsafe { crate::util::isize_to_usize(super::Py_SIZE(self.ptr.as_ptr())) }
    }
}
