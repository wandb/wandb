// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2021-2026)

#[cfg(all(target_arch = "x86_64", not(target_feature = "avx2")))]
pub(crate) fn is_valid_utf8(buf: &[u8]) -> bool {
    if std::is_x86_feature_detected!("avx2") {
        unsafe { simdutf8::basic::imp::x86::avx2::validate_utf8(buf).is_ok() }
    } else {
        encoding_rs::Encoding::utf8_valid_up_to(buf) == buf.len()
    }
}

#[cfg(all(target_arch = "x86_64", target_feature = "avx2"))]
pub(crate) fn is_valid_utf8(buf: &[u8]) -> bool {
    simdutf8::basic::from_utf8(buf).is_ok()
}

#[cfg(target_arch = "aarch64")]
pub(crate) fn is_valid_utf8(buf: &[u8]) -> bool {
    unsafe { simdutf8::basic::imp::aarch64::neon::validate_utf8(buf).is_ok() }
}

#[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
pub(crate) fn is_valid_utf8(buf: &[u8]) -> bool {
    std::str::from_utf8(buf).is_ok()
}
