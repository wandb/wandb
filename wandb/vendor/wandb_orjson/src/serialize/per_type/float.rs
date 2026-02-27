// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

// ---
// Modified by Weights & Biases on 2026-02-24.
// See WANDB_VENDOR.md for details.
// ---

use crate::ffi::PyFloatRef;
use crate::opt::{Opt, FAIL_ON_INVALID_FLOAT};
use crate::serialize::error::SerializeError;
use serde::ser::{Serialize, Serializer};

pub(crate) struct FloatSerializer {
    ob: PyFloatRef,
    opts: Opt,
}

impl FloatSerializer {
    pub fn new(ptr: PyFloatRef, opts: Opt) -> Self {
        FloatSerializer { ob: ptr, opts: opts }
    }
}

impl Serialize for FloatSerializer {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let val = self.ob.value();
        if opt_enabled!(self.opts, FAIL_ON_INVALID_FLOAT) {
            if val.is_nan() || val.is_infinite() {
                err!(SerializeError::InvalidFloat);
            }
        }
        serializer.serialize_f64(val)
    }
}
