// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2026), Eric Jolibois (2021)

mod backend;
#[cfg(not(Py_GIL_DISABLED))]
mod cache;
mod deserializer;
mod error;
mod input;
mod pyobject;

#[cfg(not(Py_GIL_DISABLED))]
pub(crate) use cache::{KEY_MAP, KeyMap};
pub(crate) use deserializer::deserialize;
pub(crate) use error::DeserializeError;
