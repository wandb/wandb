// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2022-2026), Eric Jolibois (2021)

use std::borrow::Cow;

pub(crate) struct DeserializeError<'a> {
    pub message: Cow<'a, str>,
    pub data: Option<&'a str>,
    pub pos: i64,
}

impl<'a> DeserializeError<'a> {
    #[cold]
    pub fn invalid(message: Cow<'a, str>) -> Self {
        DeserializeError {
            message: message,
            data: None,
            pos: 0,
        }
    }

    #[cold]
    pub fn from_yyjson(message: Cow<'a, str>, pos: i64, data: &'a str) -> Self {
        DeserializeError {
            message: message,
            data: Some(data),
            pos: pos,
        }
    }

    /// Return position of the error in the deserialized data
    #[cold]
    #[cfg_attr(feature = "optimize", optimize(size))]
    pub fn pos(&self) -> i64 {
        match self.data {
            Some(as_str) => {
                #[allow(clippy::cast_sign_loss)]
                let pos = self.pos as usize;
                #[allow(clippy::cast_possible_wrap)]
                let res = as_str[0..pos].chars().count() as i64; // stmt_expr_attributes
                res
            }
            None => 0,
        }
    }
}
