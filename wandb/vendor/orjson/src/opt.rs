// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2020-2025)

pub(crate) type Opt = u32;

pub(crate) const INDENT_2: Opt = 1;
pub(crate) const NAIVE_UTC: Opt = 1 << 1;
pub(crate) const NON_STR_KEYS: Opt = 1 << 2;
pub(crate) const OMIT_MICROSECONDS: Opt = 1 << 3;
pub(crate) const SERIALIZE_NUMPY: Opt = 1 << 4;
pub(crate) const SORT_KEYS: Opt = 1 << 5;
pub(crate) const STRICT_INTEGER: Opt = 1 << 6;
pub(crate) const UTC_Z: Opt = 1 << 7;
pub(crate) const PASSTHROUGH_SUBCLASS: Opt = 1 << 8;
pub(crate) const PASSTHROUGH_DATETIME: Opt = 1 << 9;
pub(crate) const APPEND_NEWLINE: Opt = 1 << 10;
pub(crate) const PASSTHROUGH_DATACLASS: Opt = 1 << 11;
pub(crate) const FAIL_ON_INVALID_FLOAT: Opt = 1 << 12;

// deprecated
pub(crate) const SERIALIZE_DATACLASS: Opt = 0;
pub(crate) const SERIALIZE_UUID: Opt = 0;

pub(crate) const SORT_OR_NON_STR_KEYS: Opt = SORT_KEYS | NON_STR_KEYS;

pub(crate) const NOT_PASSTHROUGH: Opt =
    !(PASSTHROUGH_DATETIME | PASSTHROUGH_DATACLASS | PASSTHROUGH_SUBCLASS);

#[allow(clippy::cast_possible_wrap)]
pub(crate) const MAX_OPT: i32 = (APPEND_NEWLINE
    | FAIL_ON_INVALID_FLOAT
    | INDENT_2
    | NAIVE_UTC
    | NON_STR_KEYS
    | OMIT_MICROSECONDS
    | PASSTHROUGH_DATETIME
    | PASSTHROUGH_DATACLASS
    | PASSTHROUGH_SUBCLASS
    | SERIALIZE_DATACLASS
    | SERIALIZE_NUMPY
    | SERIALIZE_UUID
    | SORT_KEYS
    | STRICT_INTEGER
    | UTC_Z) as i32;
