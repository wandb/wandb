// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

#[cfg(feature = "avx512")]
#[cfg(CPython)]
mod avx512;
mod object;
#[cfg(CPython)]
mod pyunicode_new;
#[cfg(CPython)]
mod scalar;

pub(crate) use object::{PyStrRef, PyStrSubclassRef, set_str_create_fn};
