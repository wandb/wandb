// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2023-2026)

#[allow(unused)]
use super::Py_TPFLAGS_LONG_SUBCLASS;
use super::{PyLong_FromLongLong, PyLong_FromUnsignedLongLong, PyObject};
use crate::opt::{MAX_OPT, Opt};

// longintrepr.h, _longobject, _PyLongValue

#[allow(dead_code)]
#[cfg(Py_3_12)]
#[allow(non_upper_case_globals)]
const SIGN_MASK: usize = 3;

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[allow(non_upper_case_globals)]
const NON_SIZE_BITS: usize = 3;

#[cfg(Py_3_12)]
#[repr(C)]
pub(crate) struct _PyLongValue {
    pub lv_tag: usize,
    pub ob_digit: u32,
}

#[cfg(all(Py_3_12, feature = "inline_int"))]
#[repr(C)]
pub(crate) struct PyLongObject {
    pub ob_base: super::PyObject,
    pub long_value: _PyLongValue,
}

#[allow(dead_code)]
#[cfg(all(not(Py_3_12), feature = "inline_int"))]
#[repr(C)]
pub(crate) struct PyLongObject {
    pub ob_base: super::PyVarObject,
    pub ob_digit: u32,
}

pub(crate) enum PyIntError {
    NotType,
    #[cfg(not(feature = "inline_int"))]
    NotSigned,
    Exceeds64Bit,
}

pub(crate) enum PyIntOptConversionError {
    InvalidRange,
}

#[allow(unused)]
#[derive(PartialEq)]
pub(crate) enum PyIntKind {
    U32,
    I32,
    U64,
    I64,
}

#[derive(Clone)]
#[repr(transparent)]
pub(crate) struct PyIntRef {
    ptr: core::ptr::NonNull<PyObject>,
}

unsafe impl Send for PyIntRef {}
unsafe impl Sync for PyIntRef {}

impl PartialEq for PyIntRef {
    fn eq(&self, other: &Self) -> bool {
        self.ptr == other.ptr
    }
}

impl PyIntRef {
    #[inline]
    pub fn from_ptr(ptr: *mut pyo3_ffi::PyObject) -> Result<Self, PyIntError> {
        unsafe {
            debug_assert!(!ptr.is_null());
            if ob_type!(ptr) == crate::typeref::INT_TYPE {
                Ok(Self {
                    ptr: core::ptr::NonNull::new_unchecked(ptr),
                })
            } else {
                Err(PyIntError::NotType)
            }
        }
    }
    #[inline]
    pub unsafe fn from_ptr_unchecked(ptr: *mut PyObject) -> Self {
        unsafe {
            debug_assert!(!ptr.is_null());
            debug_assert!(
                ob_type!(ptr) == crate::typeref::INT_TYPE
                    || is_subclass_by_flag!(tp_flags!(ob_type!(ptr)), Py_TPFLAGS_LONG_SUBCLASS)
            );
            Self {
                ptr: core::ptr::NonNull::new_unchecked(ptr),
            }
        }
    }

    #[inline]
    pub fn as_ptr(&self) -> *mut PyObject {
        self.ptr.as_ptr()
    }

    #[inline]
    pub fn as_non_null_ptr(&self) -> core::ptr::NonNull<PyObject> {
        self.ptr
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    pub fn kind(&self) -> PyIntKind {
        match (self.is_signed(), self.fits_in_i32()) {
            (true, true) => PyIntKind::I32,
            (true, false) => PyIntKind::I64,
            (false, true) => PyIntKind::U32,
            (false, false) => PyIntKind::U64,
        }
    }

    #[cfg(all(Py_3_12, feature = "inline_int"))]
    #[inline]
    pub fn is_signed(&self) -> bool {
        unsafe { (*self.as_ptr().cast::<PyLongObject>()).long_value.lv_tag & SIGN_MASK != 0 }
    }

    #[cfg(all(not(Py_3_12), feature = "inline_int"))]
    #[inline]
    pub fn is_signed(&self) -> bool {
        unsafe { (*self.as_ptr().cast::<super::PyVarObject>()).ob_size < 0 }
    }

    #[cfg(all(Py_3_12, feature = "inline_int"))]
    #[inline]
    pub fn fits_in_i32(&self) -> bool {
        unsafe { (*self.as_ptr().cast::<PyLongObject>()).long_value.lv_tag < (2 << NON_SIZE_BITS) }
    }

    #[cfg(all(not(Py_3_12), feature = "inline_int"))]
    #[inline]
    pub fn fits_in_i32(&self) -> bool {
        unsafe { isize::abs(super::Py_SIZE(self.as_ptr())) == 1 }
    }

    #[cfg(all(Py_3_12, feature = "inline_int"))]
    #[inline]
    fn get_inline_value(&self) -> u32 {
        unsafe { (*self.as_ptr().cast::<PyLongObject>()).long_value.ob_digit }
    }

    #[cfg(all(not(Py_3_12), feature = "inline_int"))]
    #[inline]
    fn get_inline_value(&self) -> u32 {
        unsafe { (*self.as_ptr().cast::<PyLongObject>()).ob_digit }
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    pub unsafe fn as_u32(&self) -> u32 {
        debug_assert!(self.kind() == PyIntKind::U32);
        self.get_inline_value()
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    pub unsafe fn as_i32(&self) -> i32 {
        debug_assert!(self.kind() == PyIntKind::I32);
        -(self.get_inline_value().cast_signed())
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    fn get_64bit_value(&self) -> Result<[u8; 8], PyIntError> {
        unsafe {
            let mut buffer: [u8; 8] = [0; 8];
            let ret = crate::ffi::PyLong_AsByteArray(
                self.as_ptr().cast::<pyo3_ffi::PyLongObject>(),
                buffer.as_mut_ptr().cast::<core::ffi::c_uchar>(),
                8,
                1,
                i32::from(self.is_signed()),
            );
            if ret == -1 {
                cold_path!();
                #[cfg(not(Py_3_13))]
                ffi!(PyErr_Clear());
                Err(PyIntError::Exceeds64Bit)
            } else {
                Ok(buffer)
            }
        }
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    pub unsafe fn as_i64(&self) -> Result<i64, PyIntError> {
        debug_assert!(self.kind() == PyIntKind::I64);
        let val = self.get_64bit_value()?;
        #[allow(unnecessary_transmutes)]
        unsafe {
            Ok(core::mem::transmute::<[u8; 8], i64>(val))
        }
    }

    #[cfg(feature = "inline_int")]
    #[inline]
    pub unsafe fn as_u64(&self) -> Result<u64, PyIntError> {
        debug_assert!(self.kind() == PyIntKind::U64);
        let val = self.get_64bit_value()?;
        #[allow(unnecessary_transmutes)]
        unsafe {
            Ok(core::mem::transmute::<[u8; 8], u64>(val))
        }
    }

    #[cfg(not(feature = "inline_int"))]
    #[inline]
    pub unsafe fn as_i64(&self) -> Result<i64, PyIntError> {
        let ival = ffi!(PyLong_AsLongLong(self.as_ptr()));
        if ival == -1 && !ffi!(PyErr_Occurred()).is_null() {
            cold_path!();
            ffi!(PyErr_Clear());
            Err(PyIntError::NotSigned)
        } else {
            Ok(ival)
        }
    }

    #[cfg(not(feature = "inline_int"))]
    #[inline]
    pub unsafe fn as_u64(&self) -> Result<u64, PyIntError> {
        let uval = ffi!(PyLong_AsUnsignedLongLong(self.as_ptr()));
        if uval == u64::MAX && !ffi!(PyErr_Occurred()).is_null() {
            cold_path!();
            Err(PyIntError::Exceeds64Bit)
        } else {
            Ok(uval)
        }
    }

    #[cfg(feature = "inline_int")]
    pub fn as_opt(&self) -> Result<Opt, PyIntOptConversionError> {
        let val = self.get_inline_value();
        if val == 0 {
            Ok(val as Opt)
        } else {
            match self.kind() {
                PyIntKind::U32 => {
                    if !(0..=MAX_OPT as u32).contains(&val) {
                        Err(PyIntOptConversionError::InvalidRange)
                    } else {
                        Ok(val as Opt)
                    }
                }
                _ => Err(PyIntOptConversionError::InvalidRange),
            }
        }
    }

    #[cfg(not(feature = "inline_int"))]
    pub fn as_opt(&self) -> Result<Opt, PyIntOptConversionError> {
        match unsafe { self.as_u64() } {
            Ok(val) => {
                if !(0..=MAX_OPT as u64).contains(&val) {
                    Err(PyIntOptConversionError::InvalidRange)
                } else {
                    Ok(val as Opt)
                }
            }
            Err(_) => Err(PyIntOptConversionError::InvalidRange),
        }
    }

    #[inline]
    pub fn from_i64(value: i64) -> Self {
        unsafe {
            let ptr = PyLong_FromLongLong(value);
            debug_assert!(!ptr.is_null());
            Self::from_ptr_unchecked(ptr)
        }
    }

    #[inline]
    pub fn from_u64(value: u64) -> Self {
        unsafe {
            let ptr = PyLong_FromUnsignedLongLong(value);
            debug_assert!(!ptr.is_null());
            Self::from_ptr_unchecked(ptr)
        }
    }
}
