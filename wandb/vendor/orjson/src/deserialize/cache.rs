// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2019-2025)

use crate::str::PyStr;
use associative_cache::{AssociativeCache, Capacity2048, HashDirectMapped, RoundRobinReplacement};
use core::cell::OnceCell;

#[repr(transparent)]
pub(crate) struct CachedKey {
    ptr: PyStr,
}

unsafe impl Send for CachedKey {}
unsafe impl Sync for CachedKey {}

impl CachedKey {
    pub fn new(ptr: PyStr) -> CachedKey {
        CachedKey { ptr: ptr }
    }
    pub fn get(&mut self) -> PyStr {
        let ptr = self.ptr.as_ptr();
        debug_assert!(ffi!(Py_REFCNT(ptr)) >= 1);
        ffi!(Py_INCREF(ptr));
        self.ptr
    }
}

impl Drop for CachedKey {
    fn drop(&mut self) {
        ffi!(Py_DECREF(self.ptr.as_ptr().cast::<crate::ffi::PyObject>()));
    }
}

pub(crate) type KeyMap =
    AssociativeCache<u64, CachedKey, Capacity2048, HashDirectMapped, RoundRobinReplacement>;

pub(crate) static mut KEY_MAP: OnceCell<KeyMap> = OnceCell::new();
