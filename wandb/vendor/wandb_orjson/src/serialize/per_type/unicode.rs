// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::{PyStrRef, PyStrSubclassRef};
use crate::serialize::error::SerializeError;

use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct StrSerializer {
    ob: PyStrRef,
}

impl StrSerializer {
    pub fn new(ptr: PyStrRef) -> Self {
        StrSerializer { ob: ptr }
    }
}

impl Serialize for StrSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.ob.clone().as_str() {
            Some(uni) => serializer.serialize_str(uni),
            None => {
                cold_path!();
                err!(SerializeError::InvalidStr)
            }
        }
    }
}

#[repr(transparent)]
pub(crate) struct StrSubclassSerializer {
    ob: PyStrSubclassRef,
}

impl StrSubclassSerializer {
    pub fn new(ptr: PyStrSubclassRef) -> Self {
        StrSubclassSerializer { ob: ptr }
    }
}

impl Serialize for StrSubclassSerializer {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.ob.as_str() {
            Some(uni) => serializer.serialize_str(uni),
            None => {
                cold_path!();
                err!(SerializeError::InvalidStr)
            }
        }
    }
}
