// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::{PyFragmentRef, PyFragmentRefError};
use crate::serialize::error::SerializeError;

use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct FragmentSerializer {
    ob: PyFragmentRef,
}

impl FragmentSerializer {
    pub fn new(ob: PyFragmentRef) -> Self {
        FragmentSerializer { ob: ob }
    }
}

impl Serialize for FragmentSerializer {
    #[cold]
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.ob.value() {
            Ok(buffer) => serializer.serialize_bytes(buffer),
            Err(PyFragmentRefError::InvalidStr) => err!(SerializeError::InvalidStr),
            Err(PyFragmentRefError::InvalidFragment) => err!(SerializeError::InvalidFragment),
        }
    }
}
