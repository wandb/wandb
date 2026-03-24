// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2022-2026)

use crate::ffi::PyStrRef;

#[cfg(all(CPython, not(Py_GIL_DISABLED)))]
#[inline(always)]
pub(crate) fn get_unicode_key(key_str: &str) -> PyStrRef {
    if key_str.len() > 64 {
        cold_path!();
        PyStrRef::from_str_with_hash(key_str)
    } else {
        assume!(key_str.len() <= 64);
        let hash = xxhash_rust::xxh3::xxh3_64(key_str.as_bytes());
        unsafe {
            let entry = crate::deserialize::cache::KEY_MAP
                .get_mut()
                .unwrap_or_else(|| unreachable_unchecked!())
                .entry(&hash)
                .or_insert_with(
                    || hash,
                    || {
                        crate::deserialize::cache::CachedKey::new(PyStrRef::from_str_with_hash(
                            key_str,
                        ))
                    },
                );
            entry.get()
        }
    }
}

#[cfg(all(CPython, Py_GIL_DISABLED))]
#[inline(always)]
pub(crate) fn get_unicode_key(key_str: &str) -> PyStrRef {
    PyStrRef::from_str_with_hash(key_str)
}

#[cfg(not(CPython))]
#[inline(always)]
pub(crate) fn get_unicode_key(key_str: &str) -> PyStrRef {
    PyStrRef::from_str(key_str)
}
