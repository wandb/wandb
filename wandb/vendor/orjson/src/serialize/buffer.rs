// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use bytes::{BufMut, buf::UninitSlice};
use core::mem::MaybeUninit;

const BUFFER_LENGTH: usize = 64 - core::mem::size_of::<usize>();

/// For use to serialize fixed-size UUIDs and DateTime.
#[repr(align(64))]
pub(crate) struct SmallFixedBuffer {
    idx: usize,
    bytes: [MaybeUninit<u8>; BUFFER_LENGTH],
}

impl SmallFixedBuffer {
    #[inline]
    pub fn new() -> Self {
        Self {
            idx: 0,
            bytes: [MaybeUninit::<u8>::uninit(); BUFFER_LENGTH],
        }
    }

    #[inline]
    pub fn as_ptr(&self) -> *const u8 {
        (&raw const self.bytes).cast::<u8>()
    }

    #[inline]
    pub fn len(&self) -> usize {
        self.idx
    }
}

unsafe impl BufMut for SmallFixedBuffer {
    #[inline]
    unsafe fn advance_mut(&mut self, cnt: usize) {
        self.idx += cnt;
    }

    #[inline]
    fn chunk_mut(&mut self) -> &mut UninitSlice {
        UninitSlice::uninit(&mut self.bytes)
    }

    #[inline]
    fn remaining_mut(&self) -> usize {
        BUFFER_LENGTH - self.idx
    }

    #[inline]
    fn put_u8(&mut self, value: u8) {
        debug_assert!(self.remaining_mut() > 1);
        unsafe {
            core::ptr::write((&raw mut self.bytes).cast::<u8>().add(self.idx), value);
            self.advance_mut(1);
        };
    }

    #[inline]
    fn put_slice(&mut self, src: &[u8]) {
        debug_assert!(self.remaining_mut() > src.len());
        unsafe {
            core::ptr::copy_nonoverlapping(
                src.as_ptr(),
                (&raw mut self.bytes).cast::<u8>().add(self.idx),
                src.len(),
            );
            self.advance_mut(src.len());
        }
    }
}
