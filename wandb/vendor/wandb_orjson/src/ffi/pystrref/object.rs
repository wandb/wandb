// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2025-2026)

#[allow(unused)]
use crate::ffi::{Py_HashBuffer, Py_ssize_t, PyASCIIObject, PyCompactUnicodeObject, PyObject};
#[cfg(all(CPython, not(feature = "inline_str")))]
use crate::ffi::{PyUnicode_DATA, PyUnicode_KIND};
use crate::typeref::{EMPTY_UNICODE, STR_TYPE};
use core::ptr::NonNull;

fn to_str_via_ffi(op: *mut PyObject) -> Option<&'static str> {
    let mut str_size: Py_ssize_t = 0;
    let ptr = ffi!(PyUnicode_AsUTF8AndSize(op, &raw mut str_size)).cast::<u8>();
    if ptr.is_null() {
        cold_path!();
        None
    } else {
        #[allow(clippy::cast_sign_loss)]
        let str_usize = str_size as usize;
        Some(str_from_slice!(ptr, str_usize))
    }
}

#[cfg(all(CPython, feature = "avx512"))]
pub type StrDeserializer = unsafe fn(&str) -> *mut PyObject;

#[cfg(all(CPython, feature = "avx512"))]
static mut STR_CREATE_FN: StrDeserializer = super::scalar::str_impl_kind_scalar;

pub fn set_str_create_fn() {
    unsafe {
        #[cfg(all(CPython, feature = "avx512"))]
        if std::is_x86_feature_detected!("avx512vl") {
            STR_CREATE_FN = super::avx512::create_str_impl_avx512vl;
        }
    }
}

#[cfg(all(feature = "inline_str", Py_3_14, Py_GIL_DISABLED))]
const STATE_KIND_SHIFT: usize = 8;

#[cfg(all(feature = "inline_str", not(all(Py_3_14, Py_GIL_DISABLED))))]
const STATE_KIND_SHIFT: usize = 2;

#[cfg(feature = "inline_str")]
const STATE_KIND_MASK: u32 = 7 << STATE_KIND_SHIFT;

#[cfg(feature = "inline_str")]
const STATE_COMPACT_ASCII: u32 =
    1 << STATE_KIND_SHIFT | 1 << (STATE_KIND_SHIFT + 3) | 1 << (STATE_KIND_SHIFT + 4);

pub(crate) enum PyStrRefError {
    NotStrType,
}

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyStrRef {
    ptr: core::ptr::NonNull<pyo3_ffi::PyObject>,
}

unsafe impl Send for PyStrRef {}
unsafe impl Sync for PyStrRef {}

impl PartialEq for PyStrRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyStrRef {
    #[inline]
    pub fn from_ptr(ptr: *mut pyo3_ffi::PyObject) -> Result<Self, PyStrRefError> {
        unsafe {
            debug_assert!(!ptr.is_null());
            if ob_type!(ptr) == crate::typeref::STR_TYPE {
                Ok(Self {
                    ptr: core::ptr::NonNull::new_unchecked(ptr),
                })
            } else {
                cold_path!();
                Err(PyStrRefError::NotStrType)
            }
        }
    }

    #[inline]
    pub unsafe fn from_ptr_unchecked(ptr: *mut pyo3_ffi::PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(ob_type!(ptr) == crate::typeref::STR_TYPE);
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    pub fn empty() -> Self {
        unsafe {
            Self {
                ptr: nonnull!(use_immortal!(EMPTY_UNICODE)),
            }
        }
    }

    #[inline]
    pub fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    pub fn as_non_null_ptr(&self) -> NonNull<PyObject> {
        nonnull!(self.as_ptr())
    }

    #[cfg(CPython)]
    #[inline(always)]
    pub fn from_str_with_hash(buf: &str) -> Self {
        let mut obj = PyStrRef::from_str(buf);
        obj.set_hash();
        obj
    }

    #[cfg(CPython)]
    #[inline(always)]
    pub fn from_str(buf: &str) -> Self {
        if buf.is_empty() {
            cold_path!();
            return Self::empty();
        }
        #[cfg(not(feature = "avx512"))]
        let str_ptr = unsafe { super::scalar::str_impl_kind_scalar(buf) };
        #[cfg(feature = "avx512")]
        let str_ptr = unsafe { STR_CREATE_FN(buf) };
        debug_assert!(!str_ptr.is_null());
        Self {
            ptr: nonnull!(str_ptr),
        }
    }

    #[cfg(not(CPython))]
    #[inline(always)]
    pub fn from_str(buf: &str) -> Self {
        if buf.is_empty() {
            cold_path!();
            return Self::empty();
        }
        let str_ptr = unsafe {
            crate::ffi::PyUnicode_FromStringAndSize(
                buf.as_ptr().cast::<core::ffi::c_char>(),
                crate::util::usize_to_isize(buf.len()),
            )
        };
        debug_assert!(!str_ptr.is_null());
        Self {
            ptr: nonnull!(str_ptr),
        }
    }

    #[cfg(CPython)]
    #[allow(unused)]
    pub fn hash(&self) -> crate::ffi::Py_hash_t {
        unsafe {
            debug_assert!((*self.as_ptr().cast::<PyASCIIObject>()).hash != -1);
            (*self.as_ptr().cast::<PyASCIIObject>()).hash
        }
    }

    #[cfg(feature = "inline_str")]
    fn set_hash(&mut self) {
        unsafe {
            let ptr = self.as_ptr().cast::<PyASCIIObject>();
            let data_ptr: *mut core::ffi::c_void =
                if (*ptr).state & STATE_COMPACT_ASCII == STATE_COMPACT_ASCII {
                    ptr.offset(1).cast::<core::ffi::c_void>()
                } else {
                    ptr.cast::<PyCompactUnicodeObject>()
                        .offset(1)
                        .cast::<core::ffi::c_void>()
                };
            #[allow(clippy::cast_possible_wrap)]
            let num_bytes =
                (*ptr).length * (((*ptr).state & STATE_KIND_MASK) >> STATE_KIND_SHIFT) as isize;
            let hash = Py_HashBuffer(data_ptr, num_bytes);
            (*ptr).hash = hash;
            debug_assert!((*ptr).hash != -1);
        }
    }

    #[cfg(not(feature = "inline_str"))]
    fn set_hash(&mut self) {
        unsafe {
            let data_ptr = PyUnicode_DATA(self.as_ptr());
            #[allow(clippy::cast_possible_wrap)]
            let num_bytes = PyUnicode_KIND(self.as_ptr()) as isize * ffi!(Py_SIZE(self.as_ptr()));
            let hash = Py_HashBuffer(data_ptr, num_bytes);
            (*self.as_ptr().cast::<PyASCIIObject>()).hash = hash;
            debug_assert!(self.hash() != -1);
        }
    }

    #[inline(always)]
    #[cfg(feature = "inline_str")]
    pub fn as_str(&self) -> Option<&'static str> {
        unsafe {
            let op = self.as_ptr();
            if (*op.cast::<PyASCIIObject>()).state & STATE_COMPACT_ASCII == STATE_COMPACT_ASCII {
                let ptr = op.cast::<PyASCIIObject>().offset(1).cast::<u8>();
                let len = crate::util::isize_to_usize((*op.cast::<PyASCIIObject>()).length);
                Some(str_from_slice!(ptr, len))
            } else if (*op.cast::<PyASCIIObject>()).state & STATE_COMPACT_ASCII == 0 {
                cold_path!();
                to_str_via_ffi(op)
            } else if (*op.cast::<PyCompactUnicodeObject>()).utf8_length != 0 {
                let ptr = ((*op.cast::<PyCompactUnicodeObject>()).utf8).cast::<u8>();
                let len =
                    crate::util::isize_to_usize((*op.cast::<PyCompactUnicodeObject>()).utf8_length);
                Some(str_from_slice!(ptr, len))
            } else {
                to_str_via_ffi(op)
            }
        }
    }

    #[inline(always)]
    #[cfg(not(feature = "inline_str"))]
    pub fn as_str(&self) -> Option<&'static str> {
        to_str_via_ffi(self.as_ptr())
    }
}

#[repr(transparent)]
pub(crate) struct PyStrSubclassRef {
    ptr: NonNull<PyObject>,
}

impl PyStrSubclassRef {
    pub unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> PyStrSubclassRef {
        let ob_type = ob_type!(ptr);
        let tp_flags = tp_flags!(ob_type);
        debug_assert!(!ptr.is_null());
        debug_assert!(!is_class_by_type!(ob_type, STR_TYPE));
        debug_assert!(is_subclass_by_flag!(tp_flags, Py_TPFLAGS_UNICODE_SUBCLASS));
        PyStrSubclassRef { ptr: nonnull!(ptr) }
    }

    #[inline]
    pub fn as_ptr(&self) -> *mut pyo3_ffi::PyObject {
        self.ptr.as_ptr()
    }

    #[inline(always)]
    pub fn as_str(&self) -> Option<&'static str> {
        to_str_via_ffi(self.as_ptr())
    }
}
