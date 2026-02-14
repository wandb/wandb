// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use serde::ser::{Serialize, Serializer};
use crate::{opt::{Opt, FAIL_ON_INVALID_FLOAT}, serialize::error::SerializeError};

pub(crate) struct FloatSerializer {
    ptr: *mut crate::ffi::PyObject,
    opts: Opt,
}

impl FloatSerializer {
    pub fn new(ptr: *mut crate::ffi::PyObject, opts: Opt) -> Self {
        FloatSerializer {
            ptr: ptr,
            opts: opts,
        }
    }
}

impl Serialize for FloatSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let val = ffi!(PyFloat_AS_DOUBLE(self.ptr));

        if opt_enabled!(self.opts, FAIL_ON_INVALID_FLOAT) {
            if val.is_nan() || val.is_infinite() {
                err!(SerializeError::InvalidFloat)
            }
        }

        serializer.serialize_f64(val)
    }
}
