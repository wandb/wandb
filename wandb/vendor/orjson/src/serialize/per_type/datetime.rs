// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025), Ben Sully (2021)

use crate::opt::{OMIT_MICROSECONDS, Opt};
use crate::serialize::buffer::SmallFixedBuffer;
use crate::serialize::error::SerializeError;
use crate::serialize::per_type::datetimelike::{DateTimeError, DateTimeLike, Offset};
use crate::typeref::{
    CONVERT_METHOD_STR, DST_STR, NORMALIZE_METHOD_STR, UTCOFFSET_METHOD_STR, ZONEINFO_TYPE,
};
use serde::ser::{Serialize, Serializer};

macro_rules! write_double_digit {
    ($buf:ident, $value:ident) => {
        if $value < 10 {
            $buf.put_u8(b'0');
        }
        $buf.put_slice(itoa::Buffer::new().format($value).as_bytes());
    };
}

macro_rules! write_microsecond {
    ($buf:ident, $microsecond:ident) => {
        if $microsecond != 0 {
            let mut buf = itoa::Buffer::new();
            let formatted = buf.format($microsecond);
            $buf.put_slice(&[b'.', b'0', b'0', b'0', b'0', b'0', b'0'][..(7 - formatted.len())]);
            $buf.put_slice(formatted.as_bytes());
        }
    };
}

#[repr(transparent)]
pub(crate) struct Date {
    ptr: *mut crate::ffi::PyObject,
}

impl Date {
    pub fn new(ptr: *mut crate::ffi::PyObject) -> Self {
        Date { ptr: ptr }
    }

    #[inline(never)]
    pub fn write_buf<B>(&self, buf: &mut B)
    where
        B: bytes::BufMut,
    {
        {
            let year = ffi!(PyDateTime_GET_YEAR(self.ptr));
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
        {
            let val_py = ffi!(PyDateTime_GET_MONTH(self.ptr));
            debug_assert!(val_py >= 0);
            #[allow(clippy::cast_sign_loss)]
            let val = val_py as u32;
            write_double_digit!(buf, val);
        }
        buf.put_u8(b'-');
        {
            let val_py = ffi!(PyDateTime_GET_DAY(self.ptr));
            debug_assert!(val_py >= 0);
            #[allow(clippy::cast_sign_loss)]
            let val = val_py as u32;
            write_double_digit!(buf, val);
        }
    }
}
impl Serialize for Date {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut buf = SmallFixedBuffer::new();
        self.write_buf(&mut buf);
        serializer.serialize_unit_struct(str_from_slice!(buf.as_ptr(), buf.len()))
    }
}

pub(crate) enum TimeError {
    HasTimezone,
}

pub(crate) struct Time {
    ptr: *mut crate::ffi::PyObject,
    opts: Opt,
}

impl Time {
    pub fn new(ptr: *mut crate::ffi::PyObject, opts: Opt) -> Self {
        Time {
            ptr: ptr,
            opts: opts,
        }
    }

    #[inline(never)]
    pub fn write_buf<B>(&self, buf: &mut B) -> Result<(), TimeError>
    where
        B: bytes::BufMut,
    {
        if unsafe { (*self.ptr.cast::<crate::ffi::PyDateTime_Time>()).hastzinfo == 1 } {
            return Err(TimeError::HasTimezone);
        }
        let hour = ffi!(PyDateTime_TIME_GET_HOUR(self.ptr)) as u8;
        write_double_digit!(buf, hour);
        buf.put_u8(b':');
        let minute = ffi!(PyDateTime_TIME_GET_MINUTE(self.ptr)) as u8;
        write_double_digit!(buf, minute);
        buf.put_u8(b':');
        let second = ffi!(PyDateTime_TIME_GET_SECOND(self.ptr)) as u8;
        write_double_digit!(buf, second);
        if opt_disabled!(self.opts, OMIT_MICROSECONDS) {
            let microsecond = ffi!(PyDateTime_TIME_GET_MICROSECOND(self.ptr)) as u32;
            write_microsecond!(buf, microsecond);
        }
        Ok(())
    }
}

impl Serialize for Time {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut buf = SmallFixedBuffer::new();
        if self.write_buf(&mut buf).is_err() {
            err!(SerializeError::DatetimeLibraryUnsupported)
        }
        serializer.serialize_unit_struct(str_from_slice!(buf.as_ptr(), buf.len()))
    }
}

pub(crate) struct DateTime {
    ptr: *mut crate::ffi::PyObject,
    opts: Opt,
}

impl DateTime {
    pub fn new(ptr: *mut crate::ffi::PyObject, opts: Opt) -> Self {
        DateTime {
            ptr: ptr,
            opts: opts,
        }
    }
}

macro_rules! pydatetime_get {
    ($fn: ident, $pyfn: ident, $ty: ident) => {
        fn $fn(&self) -> $ty {
            let ret = ffi!($pyfn(self.ptr));
            debug_assert!(ret >= 0);
            #[allow(clippy::cast_sign_loss)]
            let ret2 = ret as $ty; // stmt_expr_attributes
            ret2
        }
    };
}

impl DateTimeLike for DateTime {
    pydatetime_get!(year, PyDateTime_GET_YEAR, i32);
    pydatetime_get!(month, PyDateTime_GET_MONTH, u8);
    pydatetime_get!(day, PyDateTime_GET_DAY, u8);
    pydatetime_get!(hour, PyDateTime_DATE_GET_HOUR, u8);
    pydatetime_get!(minute, PyDateTime_DATE_GET_MINUTE, u8);
    pydatetime_get!(second, PyDateTime_DATE_GET_SECOND, u8);
    pydatetime_get!(microsecond, PyDateTime_DATE_GET_MICROSECOND, u32);

    fn nanosecond(&self) -> u32 {
        self.microsecond() * 1_000
    }

    fn has_tz(&self) -> bool {
        unsafe { (*(self.ptr.cast::<crate::ffi::PyDateTime_DateTime>())).hastzinfo == 1 }
    }

    #[inline(never)]
    fn slow_offset(&self) -> Result<Offset, DateTimeError> {
        let tzinfo = ffi!(PyDateTime_DATE_GET_TZINFO(self.ptr));
        if ffi!(PyObject_HasAttr(tzinfo, CONVERT_METHOD_STR)) == 1 {
            // pendulum
            let py_offset = call_method!(self.ptr, UTCOFFSET_METHOD_STR);
            let offset = Offset {
                second: ffi!(PyDateTime_DELTA_GET_SECONDS(py_offset)),
                day: ffi!(PyDateTime_DELTA_GET_DAYS(py_offset)),
            };
            ffi!(Py_DECREF(py_offset));
            Ok(offset)
        } else if ffi!(PyObject_HasAttr(tzinfo, NORMALIZE_METHOD_STR)) == 1 {
            // pytz
            let method_ptr = call_method!(tzinfo, NORMALIZE_METHOD_STR, self.ptr);
            let py_offset = call_method!(method_ptr, UTCOFFSET_METHOD_STR);
            ffi!(Py_DECREF(method_ptr));
            let offset = Offset {
                second: ffi!(PyDateTime_DELTA_GET_SECONDS(py_offset)),
                day: ffi!(PyDateTime_DELTA_GET_DAYS(py_offset)),
            };
            ffi!(Py_DECREF(py_offset));
            Ok(offset)
        } else if ffi!(PyObject_HasAttr(tzinfo, DST_STR)) == 1 {
            // dateutil/arrow, datetime.timezone.utc
            let py_offset = call_method!(tzinfo, UTCOFFSET_METHOD_STR, self.ptr);
            let offset = Offset {
                second: ffi!(PyDateTime_DELTA_GET_SECONDS(py_offset)),
                day: ffi!(PyDateTime_DELTA_GET_DAYS(py_offset)),
            };
            ffi!(Py_DECREF(py_offset));
            Ok(offset)
        } else {
            Err(DateTimeError::LibraryUnsupported)
        }
    }

    #[inline]
    fn offset(&self) -> Result<Offset, DateTimeError> {
        if !self.has_tz() {
            Ok(Offset::default())
        } else {
            let tzinfo = ffi!(PyDateTime_DATE_GET_TZINFO(self.ptr));
            if unsafe { core::ptr::eq(ob_type!(tzinfo), ZONEINFO_TYPE) } {
                // zoneinfo
                let py_offset = call_method!(tzinfo, UTCOFFSET_METHOD_STR, self.ptr);
                let offset = Offset {
                    second: ffi!(PyDateTime_DELTA_GET_SECONDS(py_offset)),
                    day: ffi!(PyDateTime_DELTA_GET_DAYS(py_offset)),
                };
                ffi!(Py_DECREF(py_offset));
                Ok(offset)
            } else {
                self.slow_offset()
            }
        }
    }
}

impl Serialize for DateTime {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut buf = SmallFixedBuffer::new();
        if self.write_buf(&mut buf, self.opts).is_err() {
            err!(SerializeError::DatetimeLibraryUnsupported)
        }
        serializer.serialize_unit_struct(str_from_slice!(buf.as_ptr(), buf.len()))
    }
}
