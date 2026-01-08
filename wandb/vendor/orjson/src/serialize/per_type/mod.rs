// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025), Ben Sully (2021)

mod dataclass;
mod datetime;
mod pybool;
#[macro_use]
mod datetimelike;
mod default;
mod dict;
mod float;
mod fragment;
mod int;
mod list;
mod none;
mod numpy;
mod pyenum;
mod unicode;
mod uuid;

pub(crate) use dataclass::DataclassGenericSerializer;
pub(crate) use datetime::{Date, DateTime, Time};
pub(crate) use datetimelike::{DateTimeError, DateTimeLike, Offset};
pub(crate) use default::DefaultSerializer;
pub(crate) use dict::DictGenericSerializer;
pub(crate) use float::FloatSerializer;
pub(crate) use fragment::FragmentSerializer;
pub(crate) use int::IntSerializer;
pub(crate) use list::{ListTupleSerializer, ZeroListSerializer};
pub(crate) use none::NoneSerializer;
pub(crate) use numpy::{NumpyScalar, NumpySerializer, is_numpy_array, is_numpy_scalar};
pub(crate) use pybool::BoolSerializer;
pub(crate) use pyenum::EnumSerializer;
pub(crate) use unicode::{StrSerializer, StrSubclassSerializer};
pub(crate) use uuid::UUID;
