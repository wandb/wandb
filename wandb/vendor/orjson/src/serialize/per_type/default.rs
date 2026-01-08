// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::serialize::error::SerializeError;
use crate::serialize::serializer::PyObjectSerializer;

use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct DefaultSerializer<'a> {
    previous: &'a PyObjectSerializer,
}

impl<'a> DefaultSerializer<'a> {
    pub fn new(previous: &'a PyObjectSerializer) -> Self {
        Self { previous: previous }
    }
}

impl Serialize for DefaultSerializer<'_> {
    #[cold]
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self.previous.default {
            Some(callable) => {
                if self.previous.state.default_calls_limit() {
                    cold_path!();
                    err!(SerializeError::DefaultRecursionLimit)
                }
                #[cfg(not(Py_3_10))]
                let default_obj = ffi!(PyObject_CallFunctionObjArgs(
                    callable.as_ptr(),
                    self.previous.ptr,
                    core::ptr::null_mut::<crate::ffi::PyObject>()
                ));
                #[cfg(Py_3_10)]
                #[allow(clippy::cast_sign_loss)]
                let nargs = ffi!(PyVectorcall_NARGS(1)) as usize;
                #[cfg(Py_3_10)]
                let default_obj = unsafe {
                    crate::ffi::PyObject_Vectorcall(
                        callable.as_ptr(),
                        &raw const self.previous.ptr,
                        nargs,
                        core::ptr::null_mut(),
                    )
                };
                if default_obj.is_null() {
                    err!(SerializeError::UnsupportedType(nonnull!(self.previous.ptr)))
                } else {
                    let res = PyObjectSerializer::new(
                        default_obj,
                        self.previous.state.copy_for_default_call(),
                        self.previous.default,
                    )
                    .serialize(serializer);
                    ffi!(Py_DECREF(default_obj));
                    res
                }
            }
            None => err!(SerializeError::UnsupportedType(nonnull!(self.previous.ptr))),
        }
    }
}
