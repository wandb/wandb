// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2025)
// pyo3-ffi/src/impl_/mod.rs at 0.27.1

mod atomic_c_ulong {
    pub struct GetAtomicCULong<const WIDTH: usize>();

    pub trait AtomicCULongType {
        type Type;
    }
    impl AtomicCULongType for GetAtomicCULong<32> {
        type Type = core::sync::atomic::AtomicU32;
    }
    impl AtomicCULongType for GetAtomicCULong<64> {
        type Type = core::sync::atomic::AtomicU64;
    }

    pub type TYPE =
        <GetAtomicCULong<{ core::mem::size_of::<core::ffi::c_ulong>() * 8 }> as AtomicCULongType>::Type;
}

pub type AtomicCULong = atomic_c_ulong::TYPE;
