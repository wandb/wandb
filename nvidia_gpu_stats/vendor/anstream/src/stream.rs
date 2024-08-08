//! Higher-level traits to describe writeable streams

/// Required functionality for underlying [`std::io::Write`] for adaptation
#[cfg(not(all(windows, feature = "wincon")))]
pub trait RawStream: std::io::Write + IsTerminal + private::Sealed {}

/// Required functionality for underlying [`std::io::Write`] for adaptation
#[cfg(all(windows, feature = "wincon"))]
pub trait RawStream:
    std::io::Write + IsTerminal + anstyle_wincon::WinconStream + private::Sealed
{
}

impl RawStream for std::io::Stdout {}

impl RawStream for std::io::StdoutLock<'_> {}

impl RawStream for &'_ mut std::io::StdoutLock<'_> {}

impl RawStream for std::io::Stderr {}

impl RawStream for std::io::StderrLock<'_> {}

impl RawStream for &'_ mut std::io::StderrLock<'_> {}

impl RawStream for Box<dyn std::io::Write> {}

impl RawStream for &'_ mut Box<dyn std::io::Write> {}

impl RawStream for Vec<u8> {}

impl RawStream for &'_ mut Vec<u8> {}

impl RawStream for std::fs::File {}

impl RawStream for &'_ mut std::fs::File {}

#[allow(deprecated)]
impl RawStream for crate::Buffer {}

#[allow(deprecated)]
impl RawStream for &'_ mut crate::Buffer {}

/// Trait to determine if a descriptor/handle refers to a terminal/tty.
pub trait IsTerminal: private::Sealed {
    /// Returns `true` if the descriptor/handle refers to a terminal/tty.
    fn is_terminal(&self) -> bool;
}

impl IsTerminal for std::io::Stdout {
    #[inline]
    fn is_terminal(&self) -> bool {
        is_terminal_polyfill::IsTerminal::is_terminal(self)
    }
}

impl IsTerminal for std::io::StdoutLock<'_> {
    #[inline]
    fn is_terminal(&self) -> bool {
        is_terminal_polyfill::IsTerminal::is_terminal(self)
    }
}

impl IsTerminal for &'_ mut std::io::StdoutLock<'_> {
    #[inline]
    fn is_terminal(&self) -> bool {
        (**self).is_terminal()
    }
}

impl IsTerminal for std::io::Stderr {
    #[inline]
    fn is_terminal(&self) -> bool {
        is_terminal_polyfill::IsTerminal::is_terminal(self)
    }
}

impl IsTerminal for std::io::StderrLock<'_> {
    #[inline]
    fn is_terminal(&self) -> bool {
        is_terminal_polyfill::IsTerminal::is_terminal(self)
    }
}

impl IsTerminal for &'_ mut std::io::StderrLock<'_> {
    #[inline]
    fn is_terminal(&self) -> bool {
        (**self).is_terminal()
    }
}

impl IsTerminal for Box<dyn std::io::Write> {
    #[inline]
    fn is_terminal(&self) -> bool {
        false
    }
}

impl IsTerminal for &'_ mut Box<dyn std::io::Write> {
    #[inline]
    fn is_terminal(&self) -> bool {
        false
    }
}

impl IsTerminal for Vec<u8> {
    #[inline]
    fn is_terminal(&self) -> bool {
        false
    }
}

impl IsTerminal for &'_ mut Vec<u8> {
    #[inline]
    fn is_terminal(&self) -> bool {
        false
    }
}

impl IsTerminal for std::fs::File {
    #[inline]
    fn is_terminal(&self) -> bool {
        is_terminal_polyfill::IsTerminal::is_terminal(self)
    }
}

impl IsTerminal for &'_ mut std::fs::File {
    #[inline]
    fn is_terminal(&self) -> bool {
        (**self).is_terminal()
    }
}

#[allow(deprecated)]
impl IsTerminal for crate::Buffer {
    #[inline]
    fn is_terminal(&self) -> bool {
        false
    }
}

#[allow(deprecated)]
impl IsTerminal for &'_ mut crate::Buffer {
    #[inline]
    fn is_terminal(&self) -> bool {
        (**self).is_terminal()
    }
}

/// Lock a stream
pub trait AsLockedWrite: private::Sealed {
    /// Locked writer type
    type Write<'w>: RawStream + 'w
    where
        Self: 'w;

    /// Lock a stream
    fn as_locked_write(&mut self) -> Self::Write<'_>;
}

impl AsLockedWrite for std::io::Stdout {
    type Write<'w> = std::io::StdoutLock<'w>;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self.lock()
    }
}

impl AsLockedWrite for std::io::StdoutLock<'static> {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

impl AsLockedWrite for std::io::Stderr {
    type Write<'w> = std::io::StderrLock<'w>;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self.lock()
    }
}

impl AsLockedWrite for std::io::StderrLock<'static> {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

impl AsLockedWrite for Box<dyn std::io::Write> {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

impl AsLockedWrite for Vec<u8> {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

impl AsLockedWrite for std::fs::File {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

#[allow(deprecated)]
impl AsLockedWrite for crate::Buffer {
    type Write<'w> = &'w mut Self;

    #[inline]
    fn as_locked_write(&mut self) -> Self::Write<'_> {
        self
    }
}

mod private {
    pub trait Sealed {}

    impl Sealed for std::io::Stdout {}

    impl Sealed for std::io::StdoutLock<'_> {}

    impl Sealed for &'_ mut std::io::StdoutLock<'_> {}

    impl Sealed for std::io::Stderr {}

    impl Sealed for std::io::StderrLock<'_> {}

    impl Sealed for &'_ mut std::io::StderrLock<'_> {}

    impl Sealed for Box<dyn std::io::Write> {}

    impl Sealed for &'_ mut Box<dyn std::io::Write> {}

    impl Sealed for Vec<u8> {}

    impl Sealed for &'_ mut Vec<u8> {}

    impl Sealed for std::fs::File {}

    impl Sealed for &'_ mut std::fs::File {}

    #[allow(deprecated)]
    impl Sealed for crate::Buffer {}

    #[allow(deprecated)]
    impl Sealed for &'_ mut crate::Buffer {}
}
