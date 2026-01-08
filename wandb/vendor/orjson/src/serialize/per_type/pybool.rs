// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct BoolSerializer {
    ptr: *mut crate::ffi::PyObject,
}

impl BoolSerializer {
    pub fn new(ptr: *mut crate::ffi::PyObject) -> Self {
        BoolSerializer { ptr: ptr }
    }
}

impl Serialize for BoolSerializer {
    #[inline]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_bool(unsafe { core::ptr::eq(self.ptr, crate::typeref::TRUE) })
    }
}
