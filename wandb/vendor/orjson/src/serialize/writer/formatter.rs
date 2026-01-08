// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2022-2025)
// This is an adaptation of `src/value/ser.rs` from serde-json.

use crate::serialize::writer::WriteExt;
use std::io;

macro_rules! debug_assert_has_capacity {
    ($writer:expr) => {
        debug_assert!($writer.remaining_mut() > 4)
    };
}

pub(crate) trait Formatter {
    #[inline]
    fn write_null<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            writer.put_slice(b"null");
            Ok(())
        }
    }

    #[inline]
    fn write_bool<W>(&mut self, writer: &mut W, value: bool) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        reserve_minimum!(writer);
        unsafe {
            writer.put_slice(if value { b"true" } else { b"false" });
        }
        Ok(())
    }

    #[inline]
    fn write_i32<W>(&mut self, writer: &mut W, value: i32) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = itoap::write_to_ptr(writer.as_mut_buffer_ptr(), value);
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn write_i64<W>(&mut self, writer: &mut W, value: i64) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = itoap::write_to_ptr(writer.as_mut_buffer_ptr(), value);
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn write_u32<W>(&mut self, writer: &mut W, value: u32) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = itoap::write_to_ptr(writer.as_mut_buffer_ptr(), value);
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn write_u64<W>(&mut self, writer: &mut W, value: u64) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = itoap::write_to_ptr(writer.as_mut_buffer_ptr(), value);
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn write_f32<W>(&mut self, writer: &mut W, value: f32) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = ryu::raw::format32(value, writer.as_mut_buffer_ptr());
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn write_f64<W>(&mut self, writer: &mut W, value: f64) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        unsafe {
            reserve_minimum!(writer);
            let len = ryu::raw::format64(value, writer.as_mut_buffer_ptr());
            writer.advance_mut(len);
        }
        Ok(())
    }

    #[inline]
    fn begin_array<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        reserve_minimum!(writer);
        unsafe {
            writer.put_u8(b'[');
        }
        Ok(())
    }

    #[inline]
    fn end_array<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        debug_assert_has_capacity!(writer);
        unsafe {
            writer.put_u8(b']');
        }
        Ok(())
    }

    #[inline]
    fn begin_array_value<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        debug_assert_has_capacity!(writer);
        if !first {
            unsafe { writer.put_u8(b',') }
        }
        Ok(())
    }

    #[inline]
    fn end_array_value<W>(&mut self, _writer: &mut W) -> io::Result<()>
    where
        W: ?Sized,
    {
        Ok(())
    }

    #[inline]
    fn begin_object<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        reserve_minimum!(writer);
        unsafe {
            writer.put_u8(b'{');
        }
        Ok(())
    }

    #[inline]
    fn end_object<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        debug_assert_has_capacity!(writer);
        unsafe {
            writer.put_u8(b'}');
        }
        Ok(())
    }

    #[inline]
    fn begin_object_key<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        debug_assert_has_capacity!(writer);
        if !first {
            unsafe {
                writer.put_u8(b',');
            }
        }
        Ok(())
    }

    #[inline]
    fn end_object_key<W>(&mut self, _writer: &mut W) -> io::Result<()>
    where
        W: ?Sized,
    {
        Ok(())
    }

    #[inline]
    fn begin_object_value<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        debug_assert_has_capacity!(writer);
        unsafe {
            writer.put_u8(b':');
        }
        Ok(())
    }

    #[inline]
    fn end_object_value<W>(&mut self, _writer: &mut W) -> io::Result<()>
    where
        W: ?Sized,
    {
        Ok(())
    }
}

pub(crate) struct CompactFormatter;

impl Formatter for CompactFormatter {}

pub(crate) struct PrettyFormatter {
    current_indent: usize,
    has_value: bool,
}

impl PrettyFormatter {
    #[allow(clippy::new_without_default)]
    pub const fn new() -> Self {
        PrettyFormatter {
            current_indent: 0,
            has_value: false,
        }
    }
}

impl Formatter for PrettyFormatter {
    #[inline]
    fn begin_array<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        self.current_indent += 1;
        self.has_value = false;
        reserve_minimum!(writer);
        unsafe {
            writer.put_u8(b'[');
        }
        Ok(())
    }

    #[inline]
    fn end_array<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        self.current_indent -= 1;
        let num_spaces = self.current_indent * 2;
        reserve_pretty!(writer, num_spaces);

        unsafe {
            if self.has_value {
                writer.put_u8(b'\n');
                writer.put_bytes(b' ', num_spaces);
            }
            writer.put_u8(b']');
            Ok(())
        }
    }

    #[inline]
    fn begin_array_value<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        let num_spaces = self.current_indent * 2;
        reserve_pretty!(writer, num_spaces);

        unsafe {
            writer.put_slice(if first { b"\n" } else { b",\n" });
            writer.put_bytes(b' ', num_spaces);
        };
        Ok(())
    }

    #[inline]
    fn end_array_value<W>(&mut self, _writer: &mut W) -> io::Result<()>
    where
        W: ?Sized,
    {
        self.has_value = true;
        Ok(())
    }

    #[inline]
    fn begin_object<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        self.current_indent += 1;
        self.has_value = false;

        reserve_minimum!(writer);
        unsafe {
            writer.put_u8(b'{');
        }
        Ok(())
    }

    #[inline]
    fn end_object<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        self.current_indent -= 1;
        let num_spaces = self.current_indent * 2;
        reserve_pretty!(writer, num_spaces);

        unsafe {
            if self.has_value {
                writer.put_u8(b'\n');
                writer.put_bytes(b' ', num_spaces);
            }

            writer.put_u8(b'}');
            Ok(())
        }
    }

    #[inline]
    fn begin_object_key<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        let num_spaces = self.current_indent * 2;
        reserve_pretty!(writer, num_spaces);
        unsafe {
            writer.put_slice(if first { b"\n" } else { b",\n" });
            writer.put_bytes(b' ', num_spaces);
        }
        Ok(())
    }

    #[inline]
    fn begin_object_value<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + WriteExt + bytes::BufMut,
    {
        reserve_minimum!(writer);
        unsafe {
            writer.put_slice(b": ");
        }
        Ok(())
    }

    #[inline]
    fn end_object_value<W>(&mut self, _writer: &mut W) -> io::Result<()>
    where
        W: ?Sized,
    {
        self.has_value = true;
        Ok(())
    }
}
