use arrow::array::{
    BinaryArray, BooleanArray, Float32Array, Float64Array, Int8Array, Int16Array, Int32Array,
    Int64Array, ListArray, RecordBatch, StringArray, StructArray, UInt8Array, UInt16Array,
    UInt32Array, UInt64Array,
};
use arrow::buffer::OffsetBuffer;
use arrow::datatypes::{DataType, Field, Fields, Schema};
use arrow_rs_wrapper::serialize::*;
use std::sync::Arc;

/// Serializes a single-column, single-row batch and returns the raw bytes
/// with offset positioned at the start of the row data (after the header).
fn serialize_single_column(
    field: Field,
    column: Arc<dyn arrow::array::Array>,
) -> (Vec<u8>, usize) {
    let schema = Arc::new(Schema::new(vec![field]));
    let batch = RecordBatch::try_new(schema, vec![column]).unwrap();
    let buf = serialize_batches_to_kv_binary(&[batch]);

    // Header: num_columns(4) + name_len(4) + name_bytes + num_rows(4)
    let mut offset = 4; // skip num_columns
    let name_len = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap()) as usize;
    offset += 4 + name_len; // skip name
    offset += 4; // skip num_rows

    (buf, offset)
}

fn read_u32(buf: &[u8], offset: &mut usize) -> u32 {
    let v = u32::from_le_bytes(buf[*offset..*offset + 4].try_into().unwrap());
    *offset += 4;
    v
}

#[test]
fn test_serialize_empty() {
    let result = serialize_batches_to_kv_binary(&[]);
    assert!(result.is_empty());
}

#[test]
fn test_serialize_int64() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Int64, false),
        Arc::new(Int64Array::from(vec![42, -7])),
    );
    // Row 0
    assert_eq!(buf[off], TYPE_INT64);
    off += 1;
    assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), 42);
    off += 8;
    // Row 1
    assert_eq!(buf[off], TYPE_INT64);
    off += 1;
    assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), -7);
    off += 8;
    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_uint64() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::UInt64, false),
        Arc::new(UInt64Array::from(vec![u64::MAX])),
    );
    assert_eq!(buf[off], TYPE_UINT64);
    off += 1;
    assert_eq!(u64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), u64::MAX);
    off += 8;
    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_float64() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Float64, false),
        Arc::new(Float64Array::from(vec![3.14, -0.001])),
    );
    assert_eq!(buf[off], TYPE_FLOAT64);
    off += 1;
    let v0 = f64::from_le_bytes(buf[off..off + 8].try_into().unwrap());
    assert!((v0 - 3.14).abs() < 1e-10);
    off += 8;
    assert_eq!(buf[off], TYPE_FLOAT64);
    off += 1;
    let v1 = f64::from_le_bytes(buf[off..off + 8].try_into().unwrap());
    assert!((v1 - (-0.001)).abs() < 1e-10);
    off += 8;
    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_string() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Utf8, false),
        Arc::new(StringArray::from(vec!["hello", ""])),
    );
    // Row 0: "hello"
    assert_eq!(buf[off], TYPE_STRING);
    off += 1;
    let len0 = read_u32(&buf, &mut off);
    assert_eq!(len0, 5);
    assert_eq!(&buf[off..off + 5], b"hello");
    off += 5;

    // Row 1: ""
    assert_eq!(buf[off], TYPE_STRING);
    off += 1;
    let len1 = read_u32(&buf, &mut off);
    assert_eq!(len1, 0);

    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_bool() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Boolean, false),
        Arc::new(BooleanArray::from(vec![true, false, true])),
    );
    for expected in [1u8, 0, 1] {
        assert_eq!(buf[off], TYPE_BOOL);
        off += 1;
        assert_eq!(buf[off], expected);
        off += 1;
    }
    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_binary() {
    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Binary, false),
        Arc::new(BinaryArray::from_vec(vec![&[0xDE, 0xAD], &[0xBE, 0xEF]])),
    );
    // Row 0
    assert_eq!(buf[off], TYPE_BINARY);
    off += 1;
    let len0 = read_u32(&buf, &mut off);
    assert_eq!(len0, 2);
    assert_eq!(&buf[off..off + 2], &[0xDE, 0xAD]);
    off += 2;

    // Row 1
    assert_eq!(buf[off], TYPE_BINARY);
    off += 1;
    let len1 = read_u32(&buf, &mut off);
    assert_eq!(len1, 2);
    assert_eq!(&buf[off..off + 2], &[0xBE, 0xEF]);
    off += 2;

    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_list() {
    let values = Int64Array::from(vec![1, 2, 3, 4, 5]);
    let offsets = OffsetBuffer::new(vec![0, 2, 5].into());
    let list = ListArray::new(
        Arc::new(Field::new("item", DataType::Int64, false)),
        offsets,
        Arc::new(values),
        None,
    );

    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::List(Arc::new(Field::new("item", DataType::Int64, false))), false),
        Arc::new(list),
    );

    // Row 0: [1, 2]
    assert_eq!(buf[off], TYPE_LIST);
    off += 1;
    let count0 = read_u32(&buf, &mut off);
    assert_eq!(count0, 2);
    for expected in [1i64, 2] {
        assert_eq!(buf[off], TYPE_INT64);
        off += 1;
        assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), expected);
        off += 8;
    }

    // Row 1: [3, 4, 5]
    assert_eq!(buf[off], TYPE_LIST);
    off += 1;
    let count1 = read_u32(&buf, &mut off);
    assert_eq!(count1, 3);
    for expected in [3i64, 4, 5] {
        assert_eq!(buf[off], TYPE_INT64);
        off += 1;
        assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), expected);
        off += 8;
    }

    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_struct_as_map() {
    let struct_arr = StructArray::from(vec![
        (
            Arc::new(Field::new("x", DataType::Int64, false)),
            Arc::new(Int64Array::from(vec![10])) as Arc<dyn arrow::array::Array>,
        ),
        (
            Arc::new(Field::new("y", DataType::Utf8, false)),
            Arc::new(StringArray::from(vec!["hi"])) as Arc<dyn arrow::array::Array>,
        ),
    ]);
    let fields = Fields::from(vec![
        Field::new("x", DataType::Int64, false),
        Field::new("y", DataType::Utf8, false),
    ]);

    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Struct(fields), false),
        Arc::new(struct_arr),
    );

    // TYPE_MAP tag
    assert_eq!(buf[off], TYPE_MAP);
    off += 1;

    let num_entries = read_u32(&buf, &mut off);
    assert_eq!(num_entries, 2);

    // Entry "x" -> int64(10)
    let key_len = read_u32(&buf, &mut off) as usize;
    assert_eq!(&buf[off..off + key_len], b"x");
    off += key_len;
    assert_eq!(buf[off], TYPE_INT64);
    off += 1;
    assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), 10);
    off += 8;

    // Entry "y" -> string("hi")
    let key_len = read_u32(&buf, &mut off) as usize;
    assert_eq!(&buf[off..off + key_len], b"y");
    off += key_len;
    assert_eq!(buf[off], TYPE_STRING);
    off += 1;
    let slen = read_u32(&buf, &mut off) as usize;
    assert_eq!(&buf[off..off + slen], b"hi");
    off += slen;

    assert_eq!(off, buf.len());
}

#[test]
fn test_serialize_nullable_int64() {
    let arr = Int64Array::from(vec![Some(1), None, Some(3)]);

    let (buf, mut off) = serialize_single_column(
        Field::new("v", DataType::Int64, true),
        Arc::new(arr),
    );

    // Row 0: int64(1)
    assert_eq!(buf[off], TYPE_INT64);
    off += 1;
    assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), 1);
    off += 8;

    // Row 1: null
    assert_eq!(buf[off], TYPE_NULL);
    off += 1;

    // Row 2: int64(3)
    assert_eq!(buf[off], TYPE_INT64);
    off += 1;
    assert_eq!(i64::from_le_bytes(buf[off..off + 8].try_into().unwrap()), 3);
    off += 8;

    assert_eq!(off, buf.len());
}
