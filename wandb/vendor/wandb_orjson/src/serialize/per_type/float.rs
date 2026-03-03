// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::PyFloatRef;
use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct FloatSerializer {
    ob: PyFloatRef,
}

impl FloatSerializer {
    pub fn new(ptr: PyFloatRef) -> Self {
        FloatSerializer { ob: ptr }
    }
}

impl Serialize for FloatSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_f64(self.ob.value())
    }
}
