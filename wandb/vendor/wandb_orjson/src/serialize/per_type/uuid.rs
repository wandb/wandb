// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2018-2026)

use crate::ffi::PyUuidRef;
use crate::serialize::buffer::SmallFixedBuffer;
use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct UUID {
    ob: PyUuidRef,
}

impl UUID {
    pub fn new(ptr: PyUuidRef) -> Self {
        UUID { ob: ptr }
    }

    #[inline(never)]
    pub fn write_buf<B>(&self, buf: &mut B)
    where
        B: bytes::BufMut,
    {
        unsafe {
            let buffer_length: usize = 40;
            debug_assert!(buf.remaining_mut() >= buffer_length);
            let len = uuid::Uuid::from_u128(self.ob.value())
                .hyphenated()
                .encode_lower(core::slice::from_raw_parts_mut(
                    buf.chunk_mut().as_mut_ptr(),
                    buffer_length,
                ))
                .len();
            buf.advance_mut(len);
        }
    }
}
impl Serialize for UUID {
    #[inline(always)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut buf = SmallFixedBuffer::new();
        self.write_buf(&mut buf);
        serializer.serialize_unit_struct(str_from_slice!(buf.as_ptr(), buf.len()))
    }
}
