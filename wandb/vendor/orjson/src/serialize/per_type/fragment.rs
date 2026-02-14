// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::ffi::{Fragment, PyBytes_AS_STRING, PyBytes_GET_SIZE};
use crate::serialize::error::SerializeError;
use crate::str::PyStr;
use crate::typeref::{BYTES_TYPE, STR_TYPE};
use crate::util::isize_to_usize;

use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct FragmentSerializer {
    ptr: *mut crate::ffi::PyObject,
}

impl FragmentSerializer {
    pub fn new(ptr: *mut crate::ffi::PyObject) -> Self {
        FragmentSerializer { ptr: ptr }
    }
}

impl Serialize for FragmentSerializer {
    #[cold]
    #[inline(never)]
    #[cfg_attr(feature = "optimize", optimize(size))]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let buffer: &[u8];
        unsafe {
            let fragment: *mut Fragment = self.ptr.cast::<Fragment>();
            let ob_type = ob_type!((*fragment).contents);
            if core::ptr::eq(ob_type, BYTES_TYPE) {
                buffer = core::slice::from_raw_parts(
                    PyBytes_AS_STRING((*fragment).contents).cast::<u8>(),
                    isize_to_usize(PyBytes_GET_SIZE((*fragment).contents)),
                );
            } else if core::ptr::eq(ob_type, STR_TYPE) {
                match unsafe { PyStr::from_ptr_unchecked((*fragment).contents).to_str() } {
                    Some(uni) => buffer = uni.as_bytes(),
                    None => err!(SerializeError::InvalidStr),
                }
            } else {
                err!(SerializeError::InvalidFragment)
            }
        }
        serializer.serialize_bytes(buffer)
    }
}
