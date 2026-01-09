// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025)

use crate::ffi::{PyBytes_FromStringAndSize, PyObject};
use crate::util::usize_to_isize;
use bytes::{BufMut, buf::UninitSlice};
use core::mem::MaybeUninit;
use core::ptr::NonNull;

#[cfg(CPython)]
const BUFFER_LENGTH: usize = 1024;

#[cfg(not(CPython))]
const BUFFER_LENGTH: usize = 4096;

pub(crate) struct BytesWriter {
    cap: usize,
    len: usize,
    #[cfg(CPython)]
    bytes: *mut crate::ffi::PyBytesObject,
    #[cfg(not(CPython))]
    bytes: *mut u8,
}

impl BytesWriter {
    #[inline]
    pub fn default() -> Self {
        BytesWriter {
            cap: BUFFER_LENGTH,
            len: 0,
            #[cfg(CPython)]
            bytes: unsafe {
                PyBytes_FromStringAndSize(core::ptr::null_mut(), usize_to_isize(BUFFER_LENGTH))
                    .cast::<crate::ffi::PyBytesObject>()
            },
            #[cfg(not(CPython))]
            bytes: unsafe { crate::ffi::PyMem_Malloc(BUFFER_LENGTH).cast::<u8>() },
        }
    }

    #[cfg(CPython)]
    pub fn abort(&mut self) {
        ffi!(Py_DECREF(self.bytes.cast::<PyObject>()));
    }

    #[cfg(not(CPython))]
    pub fn abort(&mut self) {
        unsafe {
            crate::ffi::PyMem_Free(self.bytes.cast::<core::ffi::c_void>());
        }
    }

    fn append_and_terminate(&mut self, append: bool) {
        unsafe {
            if append {
                core::ptr::write(self.buffer_ptr(), b'\n');
                self.len += 1;
            }
            #[cfg(CPython)]
            core::ptr::write(self.buffer_ptr(), 0);
        }
    }

    #[cfg(CPython)]
    #[inline]
    pub fn finish(&mut self, append: bool) -> NonNull<PyObject> {
        unsafe {
            self.append_and_terminate(append);
            crate::ffi::Py_SET_SIZE(
                self.bytes.cast::<crate::ffi::PyVarObject>(),
                usize_to_isize(self.len),
            );
            self.resize(self.len);
            NonNull::new_unchecked(self.bytes.cast::<PyObject>())
        }
    }

    #[cfg(not(CPython))]
    #[inline]
    pub fn finish(&mut self, append: bool) -> NonNull<PyObject> {
        unsafe {
            self.append_and_terminate(append);
            let bytes = PyBytes_FromStringAndSize(
                self.bytes.cast::<i8>().cast_const(),
                usize_to_isize(self.len),
            );
            debug_assert!(!bytes.is_null());
            crate::ffi::PyMem_Free(self.bytes.cast::<core::ffi::c_void>());
            nonnull!(bytes)
        }
    }

    #[cfg(CPython)]
    #[inline]
    fn buffer_ptr(&self) -> *mut u8 {
        unsafe { (&raw mut (*self.bytes).ob_sval).cast::<u8>().add(self.len) }
    }

    #[cfg(not(CPython))]
    #[inline]
    fn buffer_ptr(&self) -> *mut u8 {
        debug_assert!(!self.bytes.is_null());
        unsafe { self.bytes.add(self.len) }
    }

    #[cfg(CPython)]
    #[inline]
    pub fn resize(&mut self, len: usize) {
        self.cap = len;
        unsafe {
            crate::ffi::_PyBytes_Resize(
                (&raw mut self.bytes).cast::<*mut PyObject>(),
                usize_to_isize(len),
            );
        }
    }

    #[cfg(not(CPython))]
    #[inline]
    pub fn resize(&mut self, len: usize) {
        self.cap = len;
        unsafe {
            self.bytes =
                crate::ffi::PyMem_Realloc(self.bytes.cast::<core::ffi::c_void>(), len).cast::<u8>();
            debug_assert!(!self.bytes.is_null());
        }
    }

    #[cold]
    #[inline(never)]
    fn grow(&mut self, len: usize) {
        let mut cap = self.cap;
        while len >= cap {
            cap *= 2;
        }
        self.resize(cap);
    }
}

unsafe impl BufMut for BytesWriter {
    #[inline]
    unsafe fn advance_mut(&mut self, cnt: usize) {
        self.len += cnt;
    }

    #[inline]
    fn chunk_mut(&mut self) -> &mut UninitSlice {
        unsafe {
            UninitSlice::uninit(core::slice::from_raw_parts_mut(
                self.buffer_ptr().cast::<MaybeUninit<u8>>(),
                self.remaining_mut(),
            ))
        }
    }

    #[inline]
    fn remaining_mut(&self) -> usize {
        self.cap - self.len
    }

    #[inline]
    fn put_u8(&mut self, value: u8) {
        debug_assert!(self.remaining_mut() > 1);
        unsafe {
            core::ptr::write(self.buffer_ptr(), value);
            self.advance_mut(1);
        }
    }

    #[inline]
    fn put_bytes(&mut self, val: u8, cnt: usize) {
        debug_assert!(self.remaining_mut() > cnt);
        unsafe {
            core::ptr::write_bytes(self.buffer_ptr(), val, cnt);
            self.advance_mut(cnt);
        };
    }

    #[inline]
    fn put_slice(&mut self, src: &[u8]) {
        debug_assert!(self.remaining_mut() > src.len());
        unsafe {
            core::ptr::copy_nonoverlapping(src.as_ptr(), self.buffer_ptr(), src.len());
            self.advance_mut(src.len());
        }
    }
}

// hack based on saethlin's research and patch in https://github.com/serde-rs/json/issues/766
pub(crate) trait WriteExt {
    #[inline]
    fn as_mut_buffer_ptr(&mut self) -> *mut u8 {
        core::ptr::null_mut()
    }

    #[inline]
    fn reserve(&mut self, len: usize) {
        let _ = len;
    }
}

impl WriteExt for &mut BytesWriter {
    #[inline(always)]
    fn as_mut_buffer_ptr(&mut self) -> *mut u8 {
        self.buffer_ptr()
    }

    #[inline(always)]
    fn reserve(&mut self, len: usize) {
        let end_length = self.len + len;
        if end_length >= self.cap {
            cold_path!();
            self.grow(end_length);
        }
    }
}
