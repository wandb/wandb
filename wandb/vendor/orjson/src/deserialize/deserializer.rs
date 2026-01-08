// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025), Aarni Koskela (2021), Eric Jolibois (2021)

use crate::deserialize::DeserializeError;
use crate::deserialize::utf8::read_input_to_buf;
use crate::typeref::EMPTY_UNICODE;
use core::ptr::NonNull;

pub(crate) fn deserialize(
    ptr: *mut crate::ffi::PyObject,
) -> Result<NonNull<crate::ffi::PyObject>, DeserializeError<'static>> {
    debug_assert!(ffi!(Py_REFCNT(ptr)) >= 1);
    let buffer = read_input_to_buf(ptr)?;
    debug_assert!(!buffer.is_empty());

    if buffer.len() == 2 {
        cold_path!();
        if buffer == b"[]" {
            return Ok(nonnull!(ffi!(PyList_New(0))));
        } else if buffer == b"{}" {
            return Ok(nonnull!(ffi!(PyDict_New())));
        } else if buffer == b"\"\"" {
            unsafe { return Ok(nonnull!(use_immortal!(EMPTY_UNICODE))) }
        }
    }

    let buffer_str = unsafe { core::str::from_utf8_unchecked(buffer) };

    crate::deserialize::backend::deserialize(buffer_str)
}
