// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::serialize::buffer::SmallFixedBuffer;
use crate::typeref::INT_ATTR_STR;
use core::ffi::c_uchar;
use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct UUID {
    ptr: *mut crate::ffi::PyObject,
}

impl UUID {
    pub fn new(ptr: *mut crate::ffi::PyObject) -> Self {
        UUID { ptr: ptr }
    }

    #[inline(never)]
    pub fn write_buf<B>(&self, buf: &mut B)
    where
        B: bytes::BufMut,
    {
        let value: u128;
        {
            // test_uuid_immutable, test_uuid_int
            let py_int = ffi!(PyObject_GetAttr(self.ptr, INT_ATTR_STR));
            ffi!(Py_DECREF(py_int));
            let mut buffer: [c_uchar; 16] = [0; 16];
            unsafe {
                // test_uuid_overflow
                crate::ffi::PyLong_AsByteArray(
                    py_int.cast::<crate::ffi::PyLongObject>(),
                    buffer.as_mut_ptr(),
                    16,
                    1, // little_endian
                    0, // is_signed
                );
            };
            value = u128::from_le_bytes(buffer);
        }
        unsafe {
            let buffer_length: usize = 40;
            debug_assert!(buf.remaining_mut() >= buffer_length);
            let len = uuid::Uuid::from_u128(value)
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
