use std::io;

use arrow::array::{
    Array,
    AsArray,
    BooleanArray,
    Float32Array,
    Float64Array,
    Int8Array,
    Int16Array,
    Int32Array,
    Int64Array,
    ListArray,
    MapArray,
    RecordBatch,
    StructArray,
    UInt8Array,
    UInt16Array,
    UInt32Array,
    UInt64Array,
};
use arrow::compute::cast;
use arrow::datatypes::DataType;

/// Type tags for the binary wire format between Rust and Go.
pub const TYPE_NULL: u8 = 0;
pub const TYPE_INT64: u8 = 1;
pub const TYPE_UINT64: u8 = 2;
pub const TYPE_FLOAT64: u8 = 3;
pub const TYPE_STRING: u8 = 4;
pub const TYPE_BOOL: u8 = 5;
pub const TYPE_BINARY: u8 = 6;
pub const TYPE_LIST: u8 = 7;
pub const TYPE_MAP: u8 = 8;

/// Serializes filtered RecordBatches into a compact binary key-value format
/// that Go can decode without arrow-go.
///
/// Wire format:
///   num_columns: u32
///   for each column: name_len: u32, name_bytes: [u8]
///   num_rows: u32
///   for each row, for each column: type_tag: u8, payload (type-dependent)
pub fn serialize_batches_to_kv_binary(batches: &[RecordBatch]) -> Result<Vec<u8>, io::Error> {
    if batches.is_empty() {
        return Ok(Vec::new());
    }

    let schema = batches[0].schema();
    let num_columns = schema.fields().len();
    let total_rows: usize = batches.iter().map(|b| b.num_rows()).sum();

    let mut buf = Vec::with_capacity(total_rows * num_columns * 12);

    // Header: num_columns
    buf.extend_from_slice(&(num_columns as u32).to_le_bytes());

    // Header: column names
    for field in schema.fields() {
        let name = field.name().as_bytes();
        buf.extend_from_slice(&(name.len() as u32).to_le_bytes());
        buf.extend_from_slice(name);
    }

    // Header: num_rows
    buf.extend_from_slice(&(total_rows as u32).to_le_bytes());

    // Row data
    for batch in batches {
        for row_idx in 0..batch.num_rows() {
            for col_idx in 0..batch.num_columns() {
                let col = batch.column(col_idx);
                write_value(&mut buf, col.as_ref(), row_idx)?;
            }
        }
    }

    Ok(buf)
}

fn write_value(buf: &mut Vec<u8>, arr: &dyn Array, idx: usize) -> Result<(), io::Error> {
    if arr.is_null(idx) {
        buf.push(TYPE_NULL);
        return Ok(());
    }

    match arr.data_type() {
        DataType::Int8 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<Int8Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Int16 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<Int16Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Int32 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<Int32Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Int64 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<Int64Array>().unwrap().value(idx);
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::UInt8 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<UInt8Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::UInt16 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<UInt16Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::UInt32 => {
            buf.push(TYPE_INT64);
            let v = arr.as_any().downcast_ref::<UInt32Array>().unwrap().value(idx) as i64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::UInt64 => {
            buf.push(TYPE_UINT64);
            let v = arr.as_any().downcast_ref::<UInt64Array>().unwrap().value(idx);
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Float32 => {
            buf.push(TYPE_FLOAT64);
            let v = arr.as_any().downcast_ref::<Float32Array>().unwrap().value(idx) as f64;
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Float64 => {
            buf.push(TYPE_FLOAT64);
            let v = arr.as_any().downcast_ref::<Float64Array>().unwrap().value(idx);
            buf.extend_from_slice(&v.to_le_bytes());
        }
        DataType::Utf8 | DataType::LargeUtf8 => {
            buf.push(TYPE_STRING);
            let v = arr.as_string::<i32>().value(idx);
            buf.extend_from_slice(&(v.len() as u32).to_le_bytes());
            buf.extend_from_slice(v.as_bytes());
        }
        DataType::Binary | DataType::LargeBinary | DataType::FixedSizeBinary(_) => {
            buf.push(TYPE_BINARY);
            let v = arr.as_binary::<i32>().value(idx);
            buf.extend_from_slice(&(v.len() as u32).to_le_bytes());
            buf.extend_from_slice(v);
        }
        DataType::Boolean => {
            buf.push(TYPE_BOOL);
            let v = arr.as_any().downcast_ref::<BooleanArray>().unwrap().value(idx);
            buf.push(if v { 1 } else { 0 });
        }
        DataType::List(_) => {
            buf.push(TYPE_LIST);
            let list_arr = arr.as_any().downcast_ref::<ListArray>().unwrap();
            let values = list_arr.value(idx);
            let len = values.len();
            buf.extend_from_slice(&(len as u32).to_le_bytes());
            for i in 0..len {
                write_value(buf, values.as_ref(), i)?;
            }
        }
        DataType::Dictionary(_, value_type) => {
            let casted = cast(arr, value_type).expect("failed to cast dictionary array");
            write_value(buf, casted.as_ref(), idx)?;
        }
        DataType::Struct(_) => {
            write_struct_as_map(buf, arr, idx)?;
        }
        DataType::Map(_, _) => {
            write_map_value(buf, arr, idx)?;
        }
        _ => {
            buf.push(TYPE_NULL);
        }
    }
    Ok(())
}

/// Writes a string key into the buffer: key_len:u32 + key_bytes.
fn write_key(buf: &mut Vec<u8>, key: &str) {
    buf.extend_from_slice(&(key.len() as u32).to_le_bytes());
    buf.extend_from_slice(key.as_bytes());
}

/// Serializes an Arrow Struct as TYPE_MAP { num_entries, [key, value]... }.
/// Struct field names become map keys; field values are recursively serialized.
fn write_struct_as_map(buf: &mut Vec<u8>, arr: &dyn Array, idx: usize) -> Result<(), io::Error> {
    let struct_arr = arr.as_any().downcast_ref::<StructArray>().unwrap();
    buf.push(TYPE_MAP);
    buf.extend_from_slice(&(struct_arr.num_columns() as u32).to_le_bytes());
    for (field_idx, field) in struct_arr.fields().iter().enumerate() {
        write_key(buf, field.name());
        write_value(buf, struct_arr.column(field_idx).as_ref(), idx)?;
    }
    Ok(())
}

/// Serializes an Arrow Map as TYPE_MAP { num_entries, [key, value]... }.
/// Map keys are converted to strings; values are recursively serialized.
fn write_map_value(buf: &mut Vec<u8>, arr: &dyn Array, idx: usize) -> Result<(), io::Error> {
    let map_arr = arr.as_any().downcast_ref::<MapArray>().unwrap();
    let entries = map_arr.value(idx);
    let entries_struct = entries.as_any().downcast_ref::<StructArray>().unwrap();
    let keys_arr = entries_struct.column(0);
    let values_arr = entries_struct.column(1);

    buf.push(TYPE_MAP);
    buf.extend_from_slice(&(entries.len() as u32).to_le_bytes());
    for i in 0..entries.len() {
        let key = if keys_arr.is_null(i) {
            String::new()
        } else if let DataType::Utf8 | DataType::LargeUtf8 = keys_arr.data_type() {
            keys_arr.as_string::<i32>().value(i).to_string()
        } else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("unsupported map key type: {:?}", keys_arr.data_type()),
            ));
        };
        write_key(buf, &key);
        write_value(buf, values_arr.as_ref(), i)?;
    }
    Ok(())
}
