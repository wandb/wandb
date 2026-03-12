// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2019-2026)

use crate::ffi::{Py_DECREF, Py_INCREF, PyStrRef};
use associative_cache::{AssociativeCache, Capacity2048, HashDirectMapped, RoundRobinReplacement};
use core::cell::OnceCell;

#[repr(transparent)]
pub(crate) struct CachedKey {
    ptr: PyStrRef,
}

unsafe impl Send for CachedKey {}
unsafe impl Sync for CachedKey {}

impl CachedKey {
    pub const fn new(ptr: PyStrRef) -> CachedKey {
        CachedKey { ptr: ptr }
    }
    pub fn get(&mut self) -> PyStrRef {
        let ptr = self.ptr.as_ptr();
        unsafe { Py_INCREF(ptr) };
        self.ptr.clone()
    }
}

impl Drop for CachedKey {
    fn drop(&mut self) {
        unsafe { Py_DECREF(self.ptr.as_ptr().cast::<crate::ffi::PyObject>()) };
    }
}

pub(crate) type KeyMap =
    AssociativeCache<u64, CachedKey, Capacity2048, HashDirectMapped, RoundRobinReplacement>;

pub(crate) static mut KEY_MAP: OnceCell<KeyMap> = OnceCell::new();
