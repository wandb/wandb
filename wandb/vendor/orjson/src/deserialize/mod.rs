// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025), Eric Jolibois (2021)

mod backend;
#[cfg(not(Py_GIL_DISABLED))]
mod cache;
mod deserializer;
mod error;
mod pyobject;
mod utf8;

#[cfg(not(Py_GIL_DISABLED))]
pub(crate) use cache::{KEY_MAP, KeyMap};
pub(crate) use deserializer::deserialize;
pub(crate) use error::DeserializeError;
