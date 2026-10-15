//! A protobuf wire walker for the hot record types. It hands out borrowed
//! field values so history items can be keyed and parsed without allocating
//! a string per item, which is what dominates a prost decode of a run.

#[derive(Debug, Clone, Copy)]
pub enum Value<'a> {
    Varint(u64),
    Fixed64,
    Bytes(&'a [u8]),
    Fixed32,
}

/// Calls `f` with every `(tag, value)` in `buf`. Returns false when the
/// buffer is not well formed, in which case `f` may have seen a prefix.
pub fn walk<'a>(mut buf: &'a [u8], mut f: impl FnMut(u32, Value<'a>)) -> bool {
    while !buf.is_empty() {
        let Some((key, rest)) = varint(buf) else {
            return false;
        };
        let tag = (key >> 3) as u32;
        let value = match key & 7 {
            0 => {
                let Some((v, rest)) = varint(rest) else {
                    return false;
                };
                buf = rest;
                Value::Varint(v)
            }
            1 => {
                let Some((_, rest)) = rest.split_first_chunk::<8>() else {
                    return false;
                };
                buf = rest;
                Value::Fixed64
            }
            2 => {
                let Some((len, rest)) = varint(rest) else {
                    return false;
                };
                let Some((v, rest)) = rest.split_at_checked(len as usize) else {
                    return false;
                };
                buf = rest;
                Value::Bytes(v)
            }
            5 => {
                let Some((_, rest)) = rest.split_first_chunk::<4>() else {
                    return false;
                };
                buf = rest;
                Value::Fixed32
            }
            _ => return false,
        };
        f(tag, value);
    }
    true
}

fn varint(buf: &[u8]) -> Option<(u64, &[u8])> {
    let mut value = 0u64;
    for (i, &byte) in buf.iter().take(10).enumerate() {
        value |= u64::from(byte & 0x7f) << (7 * i);
        if byte & 0x80 == 0 {
            return Some((value, &buf[i + 1..]));
        }
    }
    None
}

/// The seconds of a `google.protobuf.Timestamp`, and its nanos as a fraction.
pub fn timestamp(buf: &[u8]) -> Option<f64> {
    let mut seconds = None;
    let mut nanos = 0.0;
    walk(buf, |tag, value| match (tag, value) {
        (1, Value::Varint(s)) => seconds = Some(s as i64 as f64),
        (2, Value::Varint(n)) => nanos = n as f64 * 1e-9,
        _ => {}
    });
    seconds.map(|s| s + nanos)
}

/// A JSON number from `value_json`; strings, objects, and booleans are `None`.
pub fn number(value_json: &[u8]) -> Option<f64> {
    std::str::from_utf8(value_json).ok()?.parse().ok()
}
