// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2021-2025)

mod buffer;
mod error;
mod obtype;
mod per_type;
mod serializer;
mod state;
pub(crate) mod writer;

pub(crate) use serializer::serialize;
