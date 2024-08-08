use core::fmt::Display;
use std::path::{self, Path, PathBuf};

#[doc(hidden)]
pub trait AsDisplay<'a> {
    // TODO: convert to generic associated type.
    // https://github.com/dtolnay/thiserror/pull/253
    type Target: Display;

    fn as_display(&'a self) -> Self::Target;
}

impl<'a, T> AsDisplay<'a> for &T
where
    T: Display + 'a,
{
    type Target = &'a T;

    fn as_display(&'a self) -> Self::Target {
        *self
    }
}

impl<'a> AsDisplay<'a> for Path {
    type Target = path::Display<'a>;

    #[inline]
    fn as_display(&'a self) -> Self::Target {
        self.display()
    }
}

impl<'a> AsDisplay<'a> for PathBuf {
    type Target = path::Display<'a>;

    #[inline]
    fn as_display(&'a self) -> Self::Target {
        self.display()
    }
}
