// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright Ben Sully (2021), ijl (2020-2025)

use crate::opt::{NAIVE_UTC, OMIT_MICROSECONDS, Opt, UTC_Z};

pub(crate) enum DateTimeError {
    LibraryUnsupported,
}

macro_rules! write_double_digit {
    ($buf:ident, $value:expr) => {
        if $value < 10 {
            $buf.put_u8(b'0');
        }
        $buf.put_slice(itoa::Buffer::new().format($value).as_bytes());
    };
}

macro_rules! write_triple_digit {
    ($buf:ident, $value:expr) => {
        if $value < 100 {
            $buf.put_u8(b'0');
        }
        if $value < 10 {
            $buf.put_u8(b'0');
        }
        $buf.put_slice(itoa::Buffer::new().format($value).as_bytes());
    };
}

#[derive(Default)]
pub(crate) struct Offset {
    pub day: i32,
    pub second: i32,
}

/// Trait providing a method to write a datetime-like object to a buffer in an RFC3339-compatible format.
///
/// The provided `write_buf` method does not allocate, and is faster
/// than writing to a heap-allocated string.
pub(crate) trait DateTimeLike {
    /// Returns the year component of the datetime.
    fn year(&self) -> i32;
    /// Returns the month component of the datetime.
    fn month(&self) -> u8;
    /// Returns the day component of the datetime.
    fn day(&self) -> u8;
    /// Returns the hour component of the datetime.
    fn hour(&self) -> u8;
    /// Returns the minute component of the datetime.
    fn minute(&self) -> u8;
    /// Returns the second component of the datetime.
    fn second(&self) -> u8;
    /// Returns the number of microseconds since the whole non-leap second.
    fn microsecond(&self) -> u32;
    /// Returns the number of nanoseconds since the whole non-leap second.
    fn nanosecond(&self) -> u32;

    /// Is the object time-zone aware?
    fn has_tz(&self) -> bool;

    //// Non-zoneinfo implementation of offset()
    fn slow_offset(&self) -> Result<Offset, DateTimeError>;

    /// The offset of the timezone.
    fn offset(&self) -> Result<Offset, DateTimeError>;

    /// Write `self` to a buffer in RFC3339 format, using `opts` to
    /// customise if desired.
    #[inline(never)]
    fn write_buf<B>(&self, buf: &mut B, opts: Opt) -> Result<(), DateTimeError>
    where
        B: bytes::BufMut,
    {
        {
            let year = self.year();
            let mut yearbuf = itoa::Buffer::new();
            let formatted = yearbuf.format(year);
            if year < 1000 {
                cold_path!();
                // date-fullyear   = 4DIGIT
                buf.put_slice(&[b'0', b'0', b'0', b'0'][..(4 - formatted.len())]);
            }
            buf.put_slice(formatted.as_bytes());
        }
        buf.put_u8(b'-');
        write_double_digit!(buf, self.month());
        buf.put_u8(b'-');
        write_double_digit!(buf, self.day());
        buf.put_u8(b'T');
        write_double_digit!(buf, self.hour());
        buf.put_u8(b':');
        write_double_digit!(buf, self.minute());
        buf.put_u8(b':');
        write_double_digit!(buf, self.second());
        if opt_disabled!(opts, OMIT_MICROSECONDS) {
            let microsecond = self.microsecond();
            if microsecond != 0 {
                buf.put_u8(b'.');
                write_triple_digit!(buf, microsecond / 1_000);
                write_triple_digit!(buf, microsecond % 1_000);
                // Don't support writing nanoseconds for now.
                // If requested, something like the following should work,
                // and `SmallFixedBuffer` needs at least length 35.
                // let nanosecond = self.nanosecond();
                // if nanosecond % 1_000 != 0 {
                //     write_triple_digit!(buf, nanosecond % 1_000);
                // }
            }
        }
        if self.has_tz() || opt_enabled!(opts, NAIVE_UTC) {
            let offset = self.offset()?;
            let mut offset_second = offset.second;
            if offset_second == 0 {
                if opt_enabled!(opts, UTC_Z) {
                    buf.put_u8(b'Z');
                } else {
                    buf.put_slice(b"+00:00");
                }
            } else {
                // This branch is only really hit by the Python datetime implementation,
                // since numpy datetimes are all converted to UTC.
                if offset.day == -1 {
                    // datetime.timedelta(days=-1, seconds=68400) -> -05:00
                    buf.put_u8(b'-');
                    offset_second = 86400 - offset_second;
                } else {
                    // datetime.timedelta(seconds=37800) -> +10:30
                    buf.put_u8(b'+');
                }
                let offset_minute = offset_second / 60;
                let offset_hour = offset_minute / 60;
                write_double_digit!(buf, offset_hour);
                buf.put_u8(b':');
                let mut offset_minute_print = offset_minute % 60;
                // https://tools.ietf.org/html/rfc3339#section-5.8
                // "exactly 19 minutes and 32.13 seconds ahead of UTC"
                // "closest representable UTC offset"
                //  "+20:00"
                let offset_excess_second =
                    offset_second - (offset_minute_print * 60 + offset_hour * 3600);
                if offset_excess_second >= 30 {
                    offset_minute_print += 1;
                }
                write_double_digit!(buf, offset_minute_print);
            }
        }
        Ok(())
    }
}
