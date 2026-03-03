// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::PyBoolRef;
use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct BoolSerializer {
    ob: PyBoolRef,
}

impl BoolSerializer {
    pub fn new(ob: PyBoolRef) -> Self {
        BoolSerializer { ob: ob }
    }
}

impl Serialize for BoolSerializer {
    #[inline]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_bool(unsafe { core::ptr::eq(self.ob.as_ptr(), crate::typeref::TRUE) })
    }
}
