// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2022-2025)

#[repr(C)]
pub(crate) struct yyjson_alc {
    pub malloc: ::core::option::Option<
        unsafe extern "C" fn(
            ctx: *mut ::core::ffi::c_void,
            size: usize,
        ) -> *mut ::core::ffi::c_void,
    >,
    pub realloc: ::core::option::Option<
        unsafe extern "C" fn(
            ctx: *mut ::core::ffi::c_void,
            ptr: *mut ::core::ffi::c_void,
            size: usize,
        ) -> *mut ::core::ffi::c_void,
    >,
    pub free: ::core::option::Option<
        unsafe extern "C" fn(ctx: *mut ::core::ffi::c_void, ptr: *mut ::core::ffi::c_void),
    >,
    pub ctx: *mut ::core::ffi::c_void,
}

pub(crate) type yyjson_read_code = u32;
pub(crate) const YYJSON_READ_SUCCESS: yyjson_read_code = 0;

#[repr(C)]
pub(crate) struct yyjson_read_err {
    pub code: yyjson_read_code,
    pub msg: *const ::core::ffi::c_char,
    pub pos: usize,
}

#[repr(C)]
pub(crate) union yyjson_val_uni {
    pub u64_: u64,
    pub i64_: i64,
    pub f64_: f64,
    pub str_: *const ::core::ffi::c_char,
    pub ptr: *mut ::core::ffi::c_void,
    pub ofs: usize,
}

#[repr(C)]
pub(crate) struct yyjson_val {
    pub tag: u64,
    pub uni: yyjson_val_uni,
}

#[repr(C)]
pub(crate) struct yyjson_doc {
    pub root: *mut yyjson_val,
    pub alc: yyjson_alc,
    pub dat_read: usize,
    pub val_read: usize,
    pub str_pool: *mut ::core::ffi::c_char,
}

unsafe extern "C" {
    pub fn yyjson_read_opts(
        dat: *mut ::core::ffi::c_char,
        len: usize,
        alc: *const yyjson_alc,
        err: *mut yyjson_read_err,
    ) -> *mut yyjson_doc;

    pub fn yyjson_alc_pool_init(
        alc: *mut yyjson_alc,
        buf: *mut ::core::ffi::c_void,
        size: usize,
    ) -> bool;
}
