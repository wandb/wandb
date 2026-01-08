// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

#[cfg(feature = "avx512")]
mod avx512;
mod pystr;
mod pyunicode_new;
mod scalar;

pub(crate) use pystr::{PyStr, PyStrSubclass, set_str_create_fn};
