// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

#[macro_use]
mod escape;
#[macro_use]
mod scalar;

#[cfg(all(feature = "generic_simd", not(target_arch = "x86_64")))]
mod generic;

#[cfg(target_arch = "x86_64")]
mod sse2;

#[cfg(all(target_arch = "x86_64", feature = "avx512"))]
mod avx512;

#[cfg(all(not(target_arch = "x86_64"), not(feature = "generic_simd")))]
pub(crate) use scalar::format_escaped_str_scalar;

#[cfg(all(target_arch = "x86_64", feature = "avx512"))]
pub(crate) use avx512::format_escaped_str_impl_512vl;

#[allow(unused_imports)]
#[cfg(target_arch = "x86_64")]
pub(crate) use sse2::format_escaped_str_impl_sse2_128;

#[cfg(all(feature = "generic_simd", not(target_arch = "x86_64")))]
pub(crate) use generic::format_escaped_str_impl_generic_128;
