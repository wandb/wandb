// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2022-2025)

#[cfg(not(Py_GIL_DISABLED))]
use crate::deserialize::cache::{CachedKey, KEY_MAP};
use crate::str::PyStr;
use crate::typeref::{FALSE, NONE, TRUE};
use core::ptr::NonNull;

#[cfg(not(Py_GIL_DISABLED))]
#[inline(always)]
pub(crate) fn get_unicode_key(key_str: &str) -> PyStr {
    if key_str.len() > 64 {
        cold_path!();
        PyStr::from_str_with_hash(key_str)
    } else {
        assume!(key_str.len() <= 64);
        let hash = xxhash_rust::xxh3::xxh3_64(key_str.as_bytes());
        unsafe {
            let entry = KEY_MAP
                .get_mut()
                .unwrap_or_else(|| unreachable_unchecked!())
                .entry(&hash)
                .or_insert_with(
                    || hash,
                    || CachedKey::new(PyStr::from_str_with_hash(key_str)),
                );
            entry.get()
        }
    }
}

#[cfg(Py_GIL_DISABLED)]
#[inline(always)]
pub(crate) fn get_unicode_key(key_str: &str) -> PyStr {
    PyStr::from_str_with_hash(key_str)
}

#[allow(dead_code)]
#[inline(always)]
pub(crate) fn parse_bool(val: bool) -> NonNull<crate::ffi::PyObject> {
    if val { parse_true() } else { parse_false() }
}

#[inline(always)]
pub(crate) fn parse_true() -> NonNull<crate::ffi::PyObject> {
    nonnull!(use_immortal!(TRUE))
}

#[inline(always)]
pub(crate) fn parse_false() -> NonNull<crate::ffi::PyObject> {
    nonnull!(use_immortal!(FALSE))
}
#[inline(always)]
pub(crate) fn parse_i64(val: i64) -> NonNull<crate::ffi::PyObject> {
    nonnull!(ffi!(PyLong_FromLongLong(val)))
}

#[inline(always)]
pub(crate) fn parse_u64(val: u64) -> NonNull<crate::ffi::PyObject> {
    nonnull!(ffi!(PyLong_FromUnsignedLongLong(val)))
}

#[inline(always)]
pub(crate) fn parse_f64(val: f64) -> NonNull<crate::ffi::PyObject> {
    nonnull!(ffi!(PyFloat_FromDouble(val)))
}

#[inline(always)]
pub(crate) fn parse_none() -> NonNull<crate::ffi::PyObject> {
    nonnull!(use_immortal!(NONE))
}
