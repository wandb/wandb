// SPDX-License-Identifier: MPL-2.0
// Copyright ijl (2026)

use crate::serialize::writer::WriteExt;
use bytes::BufMut;

#[inline]
pub(crate) fn write_integer_u32<B>(buf: &mut B, val: u32)
where
    B: ?Sized + WriteExt + BufMut,
{
    write_integer(buf, val)
}

#[inline]
pub(crate) fn write_integer_i32<B>(buf: &mut B, val: i32)
where
    B: ?Sized + WriteExt + BufMut,
{
    write_integer(buf, val)
}

#[inline]
pub(crate) fn write_integer_u64<B>(buf: &mut B, val: u64)
where
    B: ?Sized + WriteExt + BufMut,
{
    write_integer(buf, val)
}

#[inline]
pub(crate) fn write_integer_i64<B>(buf: &mut B, val: i64)
where
    B: ?Sized + WriteExt + BufMut,
{
    write_integer(buf, val)
}

#[inline]
fn write_integer<B, V: itoap::Integer>(buf: &mut B, val: V)
where
    B: ?Sized + WriteExt + BufMut,
{
    unsafe {
        debug_assert!(buf.remaining_mut() >= 20);
        let len = itoap::write_to_ptr(buf.as_mut_buffer_ptr(), val);
        buf.advance_mut(len);
    }
}

#[inline]
pub(crate) fn write_float32<B>(buf: &mut B, val: f32)
where
    B: ?Sized + WriteExt + BufMut,
{
    if val.is_infinite() || val.is_nan() {
        cold_path!();
        buf.put_slice(b"null");
    } else {
        write_finite_float(buf, val)
    }
}

#[inline]
pub(crate) fn write_float64<B>(buf: &mut B, val: f64)
where
    B: ?Sized + WriteExt + BufMut,
{
    if val.is_infinite() || val.is_nan() {
        cold_path!();
        buf.put_slice(b"null");
    } else {
        write_finite_float(buf, val)
    }
}

fn write_finite_float<B, F: zmij::Float>(buf: &mut B, val: F)
where
    B: ?Sized + WriteExt + BufMut,
{
    unsafe {
        debug_assert!(buf.remaining_mut() >= 40);
        let buffer =
            unsafe { core::mem::transmute::<*mut u8, &mut zmij::Buffer>(buf.as_mut_buffer_ptr()) };
        let res = buffer.format_finite(val);
        buf.advance_mut(res.len());
    }
}
