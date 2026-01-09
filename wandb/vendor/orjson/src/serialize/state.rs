// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use crate::opt::Opt;

const RECURSION_SHIFT: usize = 24;
const RECURSION_MASK: u32 = 255 << RECURSION_SHIFT;

const DEFAULT_SHIFT: usize = 16;
const DEFAULT_MASK: u32 = 255 << DEFAULT_SHIFT;

#[repr(transparent)]
#[derive(Copy, Clone)]
pub(crate) struct SerializerState {
    // recursion: u8,
    // default_calls: u8,
    // opts: u16,
    state: u32,
}

impl SerializerState {
    #[inline(always)]
    pub fn new(opts: Opt) -> Self {
        debug_assert!(opts < u32::from(u16::MAX));
        Self { state: opts }
    }

    #[inline(always)]
    pub fn opts(self) -> u32 {
        self.state
    }

    #[inline(always)]
    pub fn recursion_limit(self) -> bool {
        self.state & RECURSION_MASK == RECURSION_MASK
    }

    #[inline(always)]
    pub fn default_calls_limit(self) -> bool {
        self.state & DEFAULT_MASK == DEFAULT_MASK
    }

    #[inline(always)]
    pub fn copy_for_recursive_call(self) -> Self {
        let opt = self.state & !RECURSION_MASK;
        let recursion = (((self.state & RECURSION_MASK) >> RECURSION_SHIFT) + 1) << RECURSION_SHIFT;
        Self {
            state: opt | recursion,
        }
    }

    #[inline(always)]
    pub fn copy_for_default_call(self) -> Self {
        let opt = self.state & !DEFAULT_MASK;
        let default_calls = (((self.state & DEFAULT_MASK) >> DEFAULT_SHIFT) + 1) << DEFAULT_SHIFT;
        Self {
            state: opt | default_calls,
        }
    }
}
