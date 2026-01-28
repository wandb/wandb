// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

use crate::serialize::serializer::PyObjectSerializer;
use crate::typeref::VALUE_STR;
use serde::ser::{Serialize, Serializer};

#[repr(transparent)]
pub(crate) struct EnumSerializer<'a> {
    previous: &'a PyObjectSerializer,
}

impl<'a> EnumSerializer<'a> {
    pub fn new(previous: &'a PyObjectSerializer) -> Self {
        Self { previous: previous }
    }
}

impl Serialize for EnumSerializer<'_> {
    #[inline(never)]
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let value = ffi!(PyObject_GetAttr(self.previous.ptr, VALUE_STR));
        debug_assert!(ffi!(Py_REFCNT(value)) >= 2);
        let ret = PyObjectSerializer::new(value, self.previous.state, self.previous.default)
            .serialize(serializer);
        ffi!(Py_DECREF(value));
        ret
    }
}
